// Hidden word games: the LLL stamp on the homepage animates into a Wordle row and opens a pop-up with two games.
(()=>{
const stamp=document.querySelector('[data-wordle-open]'),dialog=document.getElementById('wordle');
if(!stamp||!dialog)return;
const reduce=matchMedia('(prefers-reduced-motion: reduce)');
const store={get(k){try{return JSON.parse(localStorage.getItem('lll:wordle:'+k))}catch{return null}},set(k,v){try{localStorage.setItem('lll:wordle:'+k,JSON.stringify(v))}catch{}}};
const wait=ms=>new Promise(r=>setTimeout(r,ms));
const plain=k=>k.normalize('NFD').replace(/[̀-ͯ]/g,'').toUpperCase();

// Tiles flip to their new colour; for visitors who ask for reduced motion they fade instead (nothing moves).
function flip(tile,apply,half=180){
  if(reduce.matches)return tile.animate([{opacity:1},{opacity:.15}],{duration:half,easing:'ease-in'}).finished
    .then(()=>{apply(tile);return tile.animate([{opacity:.15},{opacity:1}],{duration:half,easing:'ease-out'}).finished});
  return tile.animate([{transform:'rotateX(0)'},{transform:'rotateX(90deg)'}],{duration:half,easing:'ease-in',fill:'forwards'}).finished
    .then(()=>{apply(tile);return tile.animate([{transform:'rotateX(90deg)'},{transform:'rotateX(0)'}],{duration:half,easing:'ease-out',fill:'forwards'}).finished});
}
const paint=state=>tile=>{tile.classList.remove('absent','present','correct');if(state)tile.classList.add(state)};
const bounce=tiles=>reduce.matches?Promise.resolve():Promise.all(tiles.map((t,i)=>t.animate([{transform:'translateY(0)'},{transform:'translateY(-22%)'},{transform:'translateY(0)'}],{duration:280,delay:i*90,easing:'ease-out'}).finished));
const shakeEl=el=>{if(el&&!reduce.matches)el.animate([{transform:'translateX(0)'},{transform:'translateX(-6px)'},{transform:'translateX(6px)'},{transform:'translateX(-6px)'},{transform:'translateX(0)'}],{duration:320})};

// --- Stamp animation: LLL -> empty row -> guess -> solved -> LLL. All timings (ms) in one place.
const STAMP={first:1500,rest:4000,open:450,flip:190,stagger:230,guess:1600,solved:1200,hold:1500,back:1000};
const stampTiles=[...stamp.querySelectorAll('.stamp-tile')];
const flipStamp=state=>stampTiles.forEach((t,i)=>setTimeout(()=>flip(t,paint(state),STAMP.flip),i*STAMP.stagger));
async function stampLoop(){
  await wait(STAMP.first);
  for(;;){
    if(!(document.hidden||dialog.open)){
      stamp.classList.add('is-row');await wait(STAMP.open);
      ['absent','present','correct'].forEach((s,i)=>setTimeout(()=>flip(stampTiles[i],paint(s),STAMP.flip),i*STAMP.stagger));await wait(STAMP.guess);
      flipStamp('correct');await wait(STAMP.solved);
      await bounce(stampTiles);await wait(STAMP.hold);
      flipStamp(null);await wait(STAMP.back);
      stamp.classList.remove('is-row');
    }
    await wait(STAMP.rest);
  }
}
stampLoop();

// --- Shared pop-up parts
const $=sel=>dialog.querySelector(sel);
const menuEl=$('[data-w-menu]'),playEl=$('[data-w-play]'),titleEl=$('[data-w-title]'),sizeEl=$('[data-w-size]');
const boardEl=$('.wordle-board'),keysEl=$('.wordle-keyboard'),msgEl=$('.wordle-msg'),tabsEl=$('.wordle-tabs'),resultEl=$('.wordle-result');
const anaEl=$('[data-w-anagram]'),slotsEl=$('.anagram-slots'),poolEl=$('.anagram-pool'),triedEl=$('[data-a-tried]');
const GAMES={verbum:'Verbum',anagram:'Anagramma'};
let config=null,game=null,level=null,today='',finished=false,busy=false;
const localDate=()=>{const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`};
const saveKey=()=>`${game}:${level.id}:${today}`;

function say(text,keep){msgEl.textContent=text;clearTimeout(say.t);if(text&&!keep)say.t=setTimeout(()=>msgEl.textContent='',2400)}
async function api(path,params){
  const r=await fetch(`/api/wordle${path}?level=${level.id}&date=${today}${params||''}`,{headers:{Accept:'application/json'}});
  const data=await r.json().catch(()=>({}));
  if(!r.ok||data.error)return{error:data.error||'The game is not available right now.',index:data.index};
  if(data.number)$('[data-w-number]').textContent=data.number;
  return data;
}
function showResult(data){
  resultEl.querySelector('[data-r-title]').textContent=data.solved?`Optime! Solved in ${data.used}`:'Not this time. The word was';
  resultEl.querySelector('[data-r-word]').textContent=data.answer;
  resultEl.querySelector('[data-r-meaning]').textContent=data.meaning;
  resultEl.querySelector('[data-r-points]').textContent=`${data.score.points} points`;
  resultEl.querySelector('[data-r-detail]').textContent=data.score.detail;
  resultEl.hidden=false;keysEl.hidden=true;$('.anagram-tools').hidden=true;tick();
}
function tick(){const n=new Date(),m=new Date(n);m.setHours(24,0,0,0);const s=Math.max(0,Math.floor((m-n)/1000));resultEl.querySelector('[data-r-next]').textContent=[s/3600,s%3600/60,s%60].map(x=>String(Math.floor(x)).padStart(2,'0')).join(':')}
setInterval(()=>{if(dialog.open&&!resultEl.hidden)tick()},1000);

// --- Verbum: type the word, colour clues
const KEYS=[['Q','W','E','R','T','Y','U','I','O','P'],['A','S','D','F','G','H','J','K','L'],['ENTER','Z','X','C','B','V','N','M','⌫']];
KEYS.forEach(r=>{const row=document.createElement('div');row.className='wordle-krow';r.forEach(k=>{const b=document.createElement('button');b.type='button';b.className='wordle-key'+(k.length>1?' wide':'');b.textContent=k;b.dataset.key=k;if(k==='⌫')b.setAttribute('aria-label','Delete');row.append(b)});keysEl.append(row)});
let guesses=[],rows=[],current='';
const rowEl=i=>boardEl.children[i];
function buildBoard(){
  boardEl.replaceChildren();boardEl.style.setProperty('--letters',level.letters);
  for(let r=0;r<level.tries;r++){const row=document.createElement('div');row.className='wordle-row';for(let c=0;c<level.letters;c++){const t=document.createElement('div');t.className='wordle-tile';row.append(t)}boardEl.append(row)}
}
function drawCurrent(){const r=rowEl(guesses.length);if(!r)return;[...r.children].forEach((t,i)=>{t.textContent=current[i]||'';t.classList.toggle('filled',!!current[i])})}
function paintKeys(){
  const rank={absent:1,present:2,correct:3},best={};
  guesses.forEach((g,i)=>(rows[i]||[]).forEach((s,j)=>{const k=g[j].toUpperCase();if(!best[k]||rank[s]>rank[best[k]])best[k]=s}));
  keysEl.querySelectorAll('.wordle-key').forEach(k=>paint(best[k.dataset.key])(k));
}
async function revealRow(i,animate){
  const r=rowEl(i);[...r.children].forEach((t,j)=>{t.textContent=guesses[i][j];t.classList.add('filled')});
  if(animate)await Promise.all([...r.children].map((t,j)=>wait(j*230).then(()=>flip(t,paint(rows[i][j])))));
  else [...r.children].forEach((t,j)=>paint(rows[i][j])(t));
}
async function loadVerbum(){
  guesses=(store.get(saveKey())||[]).filter(g=>typeof g==='string'&&g.length===level.letters);rows=[];current='';
  buildBoard();paintKeys();
  if(guesses.length){
    const data=await api('/check',`&guesses=${encodeURIComponent(guesses.join(','))}`);
    if(data.error){guesses=[];store.set(saveKey(),[])}
    else{rows=data.rows;guesses=guesses.slice(0,rows.length);for(let i=0;i<rows.length;i++)await revealRow(i,false);paintKeys();finished=data.finished;if(finished)showResult(data)}
  }
  drawCurrent();
}
async function submitVerbum(){
  if(current.length<level.letters){shakeEl(rowEl(guesses.length));say(`Use ${level.letters} letters`);return}
  busy=true;const attempt=[...guesses,current];const data=await api('/check',`&guesses=${encodeURIComponent(attempt.join(','))}`);
  if(data.error){busy=false;shakeEl(rowEl(guesses.length));say(data.error);return}
  guesses=attempt;rows=data.rows;current='';store.set(saveKey(),guesses);
  await revealRow(guesses.length-1,true);paintKeys();busy=false;
  if(data.finished){finished=true;if(data.solved){say('Optime!');await bounce([...rowEl(guesses.length-1).children])}await wait(500);showResult(data)}
}
function pressVerbum(k){
  if(k==='ENTER')return submitVerbum();
  if(k==='⌫'){current=current.slice(0,-1);return drawCurrent()}
  if(/^[A-Z]$/.test(k)&&current.length<level.letters){current+=k;drawCurrent()}
}

// --- Anagramma: put the mixed-up letters in order
let letters=[],order=[],placed=[],attempts=[];
function drawAnagram(){
  slotsEl.style.setProperty('--letters',level.letters);poolEl.style.setProperty('--letters',level.letters);
  slotsEl.replaceChildren(...letters.map((_,i)=>{const b=document.createElement('button');b.type='button';b.className='wordle-tile anagram-slot';const li=placed[i];
    if(li!==undefined){b.textContent=letters[li];b.classList.add('filled');b.dataset.slot=i;b.setAttribute('aria-label',`Remove ${letters[li]}`)}else{b.disabled=true;b.setAttribute('aria-label','Empty')}return b}));
  poolEl.replaceChildren(...order.map(li=>{const b=document.createElement('button');b.type='button';b.className='anagram-letter';b.textContent=letters[li];b.dataset.li=li;b.disabled=placed.includes(li)||finished;return b}));
  triedEl.textContent=attempts.length&&!finished?`Tried: ${attempts.map(a=>a.toUpperCase()).join(', ')} · ${level.tries-attempts.length} left`:'';
}
async function loadAnagram(){
  attempts=(store.get(saveKey())||[]).filter(a=>typeof a==='string'&&a.length===level.letters);placed=[];
  const puzzle=await api('/anagram');
  if(puzzle.error){say(puzzle.error,true);letters=[];order=[];drawAnagram();return}
  letters=puzzle.letters;order=letters.map((_,i)=>i);
  if(attempts.length){
    const data=await api('/anagram/check',`&attempts=${encodeURIComponent(attempts.join(','))}`);
    if(data.error){attempts=[];store.set(saveKey(),[])}
    else{attempts=attempts.slice(0,data.used);finished=data.finished;
      if(data.solved){const word=plain(data.answer);const used=new Set();placed=[...word].map(ch=>{const i=letters.findIndex((l,j)=>l===ch&&!used.has(j));used.add(i);return i})}
      drawAnagram();if(data.solved)slotsEl.querySelectorAll('.wordle-tile').forEach(paint('correct'));if(finished)showResult(data);return}
  }
  drawAnagram();
}
async function submitAnagram(){
  const word=placed.map(i=>letters[i]).join('').toLowerCase();
  busy=true;const data=await api('/anagram/check',`&attempts=${encodeURIComponent([...attempts,word].join(','))}`);busy=false;
  if(data.error){shakeEl(slotsEl);say(data.error);placed=[];drawAnagram();return}
  if(data.solved){
    attempts.push(word);store.set(saveKey(),attempts);finished=true;drawAnagram();
    const tiles=[...slotsEl.children];await Promise.all(tiles.map((t,i)=>wait(i*120).then(()=>flip(t,paint('correct')))));say('Optime!');await bounce(tiles);await wait(400);showResult(data);return}
  attempts.push(word);store.set(saveKey(),attempts);
  if(data.finished){finished=true;placed=[];drawAnagram();shakeEl(slotsEl);showResult(data);return}
  shakeEl(slotsEl);say(`Not quite. ${data.tries-data.wrong} ${data.tries-data.wrong===1?'try':'tries'} left`);placed=[];drawAnagram();
}
function placeLetter(li){if(finished||busy||placed.includes(li)||placed.length>=letters.length)return;placed.push(li);drawAnagram();if(placed.length===letters.length)submitAnagram()}
poolEl.addEventListener('click',e=>{const b=e.target.closest('.anagram-letter');if(b)placeLetter(Number(b.dataset.li))});
slotsEl.addEventListener('click',e=>{const b=e.target.closest('[data-slot]');if(b&&!finished&&!busy){placed.splice(Number(b.dataset.slot),1);drawAnagram()}});
$('[data-a-shuffle]').addEventListener('click',()=>{for(let i=order.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1));[order[i],order[j]]=[order[j],order[i]]}drawAnagram()});
$('[data-a-clear]').addEventListener('click',()=>{if(!finished&&!busy){placed=[];drawAnagram()}});
function pressAnagram(k){
  if(k==='⌫'){placed.pop();return drawAnagram()}
  if(/^[A-Z]$/.test(k)){const li=order.find(i=>letters[i]===k&&!placed.includes(i));if(li!==undefined)placeLetter(li)}
}

// --- Menu, levels and keyboard
function showMenu(){game=null;menuEl.hidden=false;playEl.hidden=true;titleEl.textContent='Choose a game';sizeEl.textContent='';say('');menuEl.querySelector('button:not([hidden])')?.focus({focusVisible:false})}
async function startGame(g){
  game=g;store.set('game',g);menuEl.hidden=true;playEl.hidden=false;titleEl.textContent=GAMES[g];
  boardEl.hidden=g!=='verbum';anaEl.hidden=g!=='anagram';
  await loadLevel(config.levels.find(l=>l.id===store.get('level'))||config.levels[0]);
}
async function loadLevel(lv){
  level=lv;store.set('level',lv.id);today=localDate();finished=false;busy=true;
  tabsEl.querySelectorAll('button').forEach(b=>b.setAttribute('aria-selected',String(Number(b.dataset.id)===lv.id)));
  sizeEl.textContent=`${lv.letters} letters · ${lv.tries} tries`;
  resultEl.hidden=true;keysEl.hidden=game!=='verbum';$('.anagram-tools').hidden=false;say('');
  if(game==='verbum')await loadVerbum();else await loadAnagram();
  busy=false;(game==='verbum'?boardEl:anaEl).focus();
}
function press(k){
  if(!game||finished||busy||!level)return;
  k=k==='BACKSPACE'?'⌫':k==='ENTER'?k:plain(k);
  if(game==='verbum')pressVerbum(k);else if(k!=='ENTER')pressAnagram(k);
}
keysEl.addEventListener('click',e=>{const b=e.target.closest('.wordle-key');if(b){press(b.dataset.key);b.blur()}});
dialog.addEventListener('keydown',e=>{
  if(e.metaKey||e.ctrlKey||e.altKey)return;
  if((e.key==='Enter'||e.key===' ')&&e.target.closest('button:not(.wordle-key)'))return;
  if(e.key==='Enter'){e.preventDefault();press('ENTER')}else if(e.key==='Backspace'){e.preventDefault();press('⌫')}else if(e.key.length===1)press(e.key);
});
tabsEl.addEventListener('click',e=>{const b=e.target.closest('button');if(b&&!busy){const lv=config.levels.find(l=>l.id===Number(b.dataset.id));if(lv&&lv!==level)loadLevel(lv)}});
menuEl.addEventListener('click',e=>{const b=e.target.closest('[data-game]');if(b)startGame(b.dataset.game)});
$('.wordle-back').addEventListener('click',showMenu);
$('.wordle-close').addEventListener('click',()=>dialog.close());

async function open(){
  dialog.showModal();
  if(!store.get('found')){$('.wordle-found').hidden=false;store.set('found',true)}
  if(!config){
    try{const r=await fetch(`/api/wordle?date=${localDate()}`,{headers:{Accept:'application/json'}});if(!r.ok)throw Error();config=await r.json()}
    catch{menuEl.hidden=true;say('The games are not available right now.',true);return}
    $('[data-w-number]').textContent=config.number;
    tabsEl.replaceChildren(...config.levels.map(l=>{const b=document.createElement('button');b.type='button';b.setAttribute('role','tab');b.dataset.id=l.id;b.textContent=l.name;return b}));
    tabsEl.hidden=config.levels.length<2;
    const on=new Set((config.games||[]).map(g=>g.id));
    menuEl.querySelectorAll('[data-game]').forEach(b=>b.hidden=!on.has(b.dataset.game));
    $('.wordle-back').hidden=on.size<2;
  }
  const only=[...menuEl.querySelectorAll('[data-game]')].filter(b=>!b.hidden);
  if(only.length===1)await startGame(only[0].dataset.game);else showMenu();
}
stamp.addEventListener('click',open);
})();
