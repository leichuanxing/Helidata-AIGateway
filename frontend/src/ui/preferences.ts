import {ref} from 'vue'
function saved(key:string,fallback:string){try{return localStorage.getItem(key)||fallback}catch{return fallback}}
export const dark=ref(saved('helidata.theme','light')==='dark'),collapsed=ref(saved('helidata.sidebar','expanded')==='collapsed')
export function applyTheme(){document.documentElement.classList.toggle('dark',dark.value)}
export function toggleTheme(){dark.value=!dark.value;applyTheme();try{localStorage.setItem('helidata.theme',dark.value?'dark':'light')}catch{}}
export function toggleSidebar(){collapsed.value=!collapsed.value;try{localStorage.setItem('helidata.sidebar',collapsed.value?'collapsed':'expanded')}catch{}}
applyTheme()
export function chartTheme(){const text=dark.value?'#aebbd0':'#667085',line=dark.value?'#2d3b50':'#edf0f5';return {animation:false,color:['#1677ff','#32ad91','#e9a23b','#e45b63'],textStyle:{color:text},legend:{textStyle:{color:text}},tooltip:{renderMode:'richText',backgroundColor:dark.value?'#202c40':'#fff',borderColor:line,textStyle:{color:dark.value?'#e4eaf4':'#344054'}},xAxis:{axisLabel:{color:text},axisLine:{lineStyle:{color:line}},splitLine:{lineStyle:{color:line}}},yAxis:{axisLabel:{color:text},nameTextStyle:{color:text},axisLine:{lineStyle:{color:line}},splitLine:{lineStyle:{color:line}}}}}
