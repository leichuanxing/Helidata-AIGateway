import {defineStore} from 'pinia'
import {ref} from 'vue'
import {api,renew,setAccess,type User} from '../api/client'
export const useAuth=defineStore('auth',()=>{
  const user=ref<User|null>(null)
  let started=false
  async function init(){if(started)return;started=true;try{user.value=(await renew()).user}catch{user.value=null}}
  async function login(username:string,password:string){const r=(await api.post('/auth/login',{username,password})).data.data;setAccess(r.access_token);user.value=r.user;started=true}
  async function logout(){try{await api.post('/auth/logout')}finally{setAccess('');user.value=null}}
  function clear(){setAccess('');user.value=null}
  return{user,init,login,logout,clear}
})
