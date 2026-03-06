const tg = window.Telegram.WebApp

tg.expand()

const API = "http://localhost:8000"

const questions = [

{
q:"Ты больше любишь:",
answers:[
{t:"logic",text:"Планировать"},
{t:"creativity",text:"Импровизировать"},
{t:"social",text:"Делать с друзьями"}
]
},

{
q:"Как принимаешь решения?",
answers:[
{t:"logic",text:"По фактам"},
{t:"emotion",text:"Интуитивно"},
{t:"social",text:"Советуюсь"}
]
},

{
q:"Твой стиль работы:",
answers:[
{t:"logic",text:"Системный"},
{t:"creativity",text:"Творческий"},
{t:"risk",text:"Экспериментальный"}
]
},

{
q:"Как относишься к риску?",
answers:[
{t:"risk",text:"Люблю риск"},
{t:"logic",text:"Просчитываю"},
{t:"emotion",text:"По настроению"}
]
},

{
q:"Как отдыхаешь?",
answers:[
{t:"creativity",text:"Творю"},
{t:"social",text:"Встречаюсь"},
{t:"logic",text:"Читаю"}
]
}

]

let index=0

const vector={
logic:0,
emotion:0,
social:0,
creativity:0,
risk:0
}

function render(){

let q=questions[index]

let html=`
<div class="card">

<div class="small">
Вопрос ${index+1} / ${questions.length}
</div>

<h3>${q.q}</h3>
`

q.answers.forEach((a,i)=>{

html+=`<button onclick="choose(${i})">${a.text}</button>`

})

html+=`</div>`

document.getElementById("app").innerHTML=html

}

function choose(i){

let type=questions[index].answers[i].t

vector[type]+=1

index++

if(index>=questions.length){

finish()

}
else{

render()

}

}

function finish(){

let total=questions.length

let norm={
logic:vector.logic/total,
emotion:vector.emotion/total,
social:vector.social/total,
creativity:vector.creativity/total,
risk:vector.risk/total
}

document.getElementById("app").innerHTML=
`<div class="card">Считаем результат...</div>`

fetch(API+"/api/compute",{

method:"POST",

headers:{
"Content-Type":"application/json"
},

body:JSON.stringify({
vector:norm
})

})
.then(r=>r.json())
.then(showResult)

}

function showResult(data){

let verdict=data.ai_verdict
? `<p>${data.ai_verdict}</p>`
: ""

document.getElementById("app").innerHTML=`

<div class="card">

<h2>${data.label}</h2>

<div class="result">
${data.rarity_percent}%
</div>

<div class="small">
Таких людей: ${data.people_like_you}
</div>

${verdict}

<button onclick="share('${data.token}')">
Поделиться
</button>

</div>

`

}

function share(token){

let url=`https://t.me/YOUR_BOT?start=${token}`

tg.openTelegramLink(url)

}

render()
