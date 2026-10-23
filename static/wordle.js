// Hidden word game: the LLL stamp on the homepage animates into a Wordle row and opens the game in a pop-up.
(()=>{
const stamp=document.querySelector('[data-wordle-open]'),dialog=document.getElementById('wordle');
if(!stamp||!dialog)return;
const reduce=matchMedia('(prefers-reduced-motion: reduce)');
const store={get(k){try{return JSON.parse(localStorage.getItem('lll:wordle:'+k))}catch{return null}},set(k,v){try{localStorage.setItem('lll:wordle:'+k,JSON.stringify(v))}catch{}}};
const wait=ms=>new Promise(r=>setTimeout(r,ms));

function flip(tile,apply,half=180){
  if(reduce.matches){apply(tile);return Promise.resolve()}
  return tile.animate([{transform:'rotateX(0)'},{transform:'rotateX(90deg)'}],{duration:half,easing:'ease-in',fill:'forwards'}).finished
    .then(()=>{apply(tile);return tile.animate([{transform:'rotateX(90deg)'},{transform:'rotateX(0)'}],{duration:half,easing:'ease-out',fill:'forwards'}).finished});
}
const paint=state=>tile=>{tile.classList.remove('absent','present','correct');if(state)tile.classList.add(state)};
const bounce=tiles=>reduce.matches?Promise.resolve():Promise.all(tiles.map((t,i)=>t.animate([{transform:'translateY(0)'},{transform:'translateY(-22%)'},{transform:'translateY(0)'}],{duration:280,delay:i*90,easing:'ease-out'}).finished));

// --- Stamp animation: LLL -> empty row -> guess -> solved -> LLL, about every 13 seconds
const stampTiles=[...stamp.querySelectorAll('.stamp-tile')];
async function stampLoop(){
  for(;;){
    await wait(7000);
    if(reduce.matches||document.hidden||dialog.open)continue;
    stamp.classList.add('is-row');await wait(450);
    for(const [i,s] of ['absent','present','correct'].entries())setTimeout(()=>flip(stampTiles[i],paint(s),190),i*230);await wait(1300);
    for(let i=0;i<3;i++)setTimeout(()=>flip(stampTiles[i],paint('correct'),190),i*230);await wait(1000);
    await bounce(stampTiles);await wait(1100);
    for(let i=0;i<3;i++)setTimeout(()=>flip(stampTiles[i],paint(null),190),i*230);await wait(900);
    stamp.classList.remove('is-row');
  }
}
stampLoop();

// --- Game
const $=sel=>dialog.querySelector(sel);
const boardEl=$('.wordle-board'),keysEl=$('.wordle-keyboard'),msgEl=$('.wordle-msg'),tabsEl=$('.wordle-tabs'),resultEl=$('.wordle-result');
const KEYS=[['Q','W','E','R','T','Y','U','I','O','P'],['A','S','D','F','G','H','J','K','L'],['ENTER','Z','X','C','B','V','N','M','⌫']];
let config=null,level=null,guesses=[],rows=[],current='',finished=false,busy=false,today='';
const localDate=()=>{const d=new Date();return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`};

KEYS.forEach(r=>{const row=document.createElement('div');row.className='wordle-krow';r.forEach(k=>{const b=document.createElement('button');b.type='button';b.className='wordle-key'+(k.length>1?' wide':'');b.textContent=k;b.dataset.key=k;if(k==='⌫')b.setAttribute('aria-label','Delete');row.append(b)});keysEl.append(row)});

function say(text,keep){msgEl.textContent=text;clearTimeout(say.t);if(text&&!keep)say.t=setTimeout(()=>msgEl.textContent='',2200)}
function buildBoard(){
  boardEl.replaceChildren();boardEl.style.setProperty('--letters',level.letters);
  for(let r=0;r<level.tries;r++){const row=document.createElement('div');row.className='wordle-row';for(let c=0;c<level.letters;c++){const t=document.createElement('div');t.className='wordle-tile';row.append(t)}boardEl.append(row)}
}
const rowEl=i=>boardEl.children[i];
function drawCurrent(){const r=rowEl(guesses.length);if(!r)return;[...r.children].forEach((t,i)=>{t.textContent=current[i]||'';t.classList.toggle('filled',!!current[i])})}
function paintKeys(){
  const rank={absent:1,present:2,correct:3},best={};
  guesses.forEach((g,i)=>(rows[i]||[]).forEach((s,j)=>{const k=g[j].toUpperCase();if(!best[k]||rank[s]>rank[best[k]])best[k]=s}));
  keysEl.querySelectorAll('.wordle-key').forEach(k=>{paint(best[k.dataset.key])(k)});
}
async function revealRow(i,animate){
  const r=rowEl(i);[...r.children].forEach((t,j)=>{t.textContent=guesses[i][j];t.classList.add('filled')});
  if(animate&&!reduce.matches)await Promise.all([...r.children].map((t,j)=>wait(j*230).then(()=>flip(t,paint(rows[i][j])))));
  else [...r.children].forEach((t,j)=>paint(rows[i][j])(t));
}
async function check(list){
  const url=`/api/wordle/check?level=${level.id}&date=${today}&guesses=${encodeURIComponent(list.join(','))}`;
  const r=await fetch(url,{headers:{Accept:'application/json'}});
  const data=await r.json().catch(()=>({}));
  if(!r.ok||data.error)return{error:data.error||'The game is not available right now.',index:data.index};
  if(data.number)$('[data-w-number]').textContent=data.number;
  return data;
}
function showResult(data){
  resultEl.querySelector('[data-r-title]').textContent=data.solved?`Optime! Solved in ${data.rows.length}`:'Not this time. The word was';
  resultEl.querySelector('[data-r-word]').textContent=data.answer;
  resultEl.querySelector('[data-r-meaning]').textContent=data.meaning;
  resultEl.querySelector('[data-r-points]').textContent=`${data.score.points} points`;
  resultEl.querySelector('[data-r-detail]').textContent=data.score.detail;
  resultEl.hidden=false;keysEl.hidden=true;tick();
}
function tick(){const n=new Date(),m=new Date(n);m.setHours(24,0,0,0);const s=Math.max(0,Math.floor((m-n)/1000));const el=resultEl.querySelector('[data-r-next]');if(el)el.textContent=[s/3600,s%3600/60,s%60].map(x=>String(Math.floor(x)).padStart(2,'0')).join(':')}
setInterval(()=>{if(dialog.open&&!resultEl.hidden)tick()},1000);

async function loadLevel(lv){
  level=lv;store.set('level',lv.id);today=localDate();
  tabsEl.querySelectorAll('button').forEach(b=>b.setAttribute('aria-selected',String(Number(b.dataset.id)===lv.id)));
  $('[data-w-size]').textContent=`${lv.letters} letters · ${lv.tries} tries`;
  guesses=(store.get(`game:${lv.id}:${today}`)||[]).filter(g=>typeof g==='string'&&g.length===lv.letters);rows=[];current='';finished=false;busy=true;
  resultEl.hidden=true;keysEl.hidden=false;say('');buildBoard();paintKeys();
  if(guesses.length){
    const data=await check(guesses);
    if(data.error){guesses=[];store.set(`game:${lv.id}:${today}`,[]);}
    else{rows=data.rows;guesses=guesses.slice(0,rows.length);for(let i=0;i<rows.length;i++)await revealRow(i,false);paintKeys();finished=data.finished;if(finished)showResult(data)}
  }
  busy=false;drawCurrent();
}
async function submit(){
  if(finished||busy)return;
  if(current.length<level.letters){shake();say(`Use ${level.letters} letters`);return}
  busy=true;const attempt=[...guesses,current];const data=await check(attempt);
  if(data.error){busy=false;shake();say(data.error);return}
  guesses=attempt;rows=data.rows;current='';store.set(`game:${level.id}:${today}`,guesses);
  await revealRow(guesses.length-1,true);paintKeys();busy=false;
  if(data.finished){finished=true;if(data.solved){say('Optime!');await bounce([...rowEl(guesses.length-1).children])}await wait(500);showResult(data)}
}
function shake(){const r=rowEl(guesses.length);if(!r||reduce.matches)return;r.animate([{transform:'translateX(0)'},{transform:'translateX(-6px)'},{transform:'translateX(6px)'},{transform:'translateX(-6px)'},{transform:'translateX(0)'}],{duration:320})}
function press(k){
  if(finished||busy||!level)return;
  if(k==='ENTER')return submit();
  if(k==='⌫'||k==='BACKSPACE'){current=current.slice(0,-1);return drawCurrent()}
  k=k.normalize('NFD').replace(/[̀-ͯ]/g,'').toUpperCase();
  if(/^[A-Z]$/.test(k)&&current.length<level.letters){current+=k;drawCurrent()}
}
keysEl.addEventListener('click',e=>{const b=e.target.closest('.wordle-key');if(b){press(b.dataset.key);b.blur()}});
dialog.addEventListener('keydown',e=>{
  if(e.metaKey||e.ctrlKey||e.altKey)return;
  if((e.key==='Enter'||e.key===' ')&&e.target.closest('button:not(.wordle-key)'))return;
  if(e.key==='Enter'){e.preventDefault();press('ENTER')}else if(e.key==='Backspace'){e.preventDefault();press('⌫')}else if(e.key.length===1)press(e.key);
});
tabsEl.addEventListener('click',e=>{const b=e.target.closest('button');if(b&&!busy){const lv=config.levels.find(l=>l.id===Number(b.dataset.id));if(lv&&lv!==level)loadLevel(lv).then(()=>boardEl.focus())}});
$('.wordle-close').addEventListener('click',()=>dialog.close());

async function open(){
  dialog.showModal();
  if(!store.get('found')){$('.wordle-found').hidden=false;store.set('found',true)}
  if(!config){
    try{const r=await fetch('/api/wordle',{headers:{Accept:'application/json'}});if(!r.ok)throw Error();config=await r.json()}
    catch{say('The game is not available right now.',true);return}
    $('[data-w-number]').textContent=config.number;
    tabsEl.replaceChildren(...config.levels.map(l=>{const b=document.createElement('button');b.type='button';b.setAttribute('role','tab');b.dataset.id=l.id;b.textContent=l.name;return b}));
    tabsEl.hidden=config.levels.length<2;
    await loadLevel(config.levels.find(l=>l.id===store.get('level'))||config.levels[0]);
  }else if(today!==localDate())await loadLevel(level);
  boardEl.focus();
}
stamp.addEventListener('click',open);
})();
