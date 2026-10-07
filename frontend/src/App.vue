<script setup lang="ts">
import {computed,ref,onMounted} from 'vue'
import {branding,loadBranding} from './ui/branding'
import {useRoute,useRouter} from 'vue-router'
import {useAuth} from './stores/auth'
import {dark,collapsed,toggleTheme,toggleSidebar} from './ui/preferences'
import {navigating} from './ui/navigation'
const route=useRoute(),router=useRouter(),auth=useAuth(),help=ref(false),about=ref(false),version=ref('')
onMounted(loadBranding)
const operationsReady=import.meta.env.VITE_OPERATIONS_READY!=='false'
const portalMode=computed(()=>route.path.startsWith('/portal/')||auth.user?.role==='user')
const links=computed(()=>portalMode.value?[
  {to:'/portal/models',label:'模型广场',icon:'dashboard'},
  {to:'/portal/api-keys',label:'API Keys',icon:'key'},
  {to:'/portal/usage',label:'用量统计',icon:'chart'}
]:[
  {to:'/admin/dashboard',label:'概览',icon:'dashboard'},
  {to:'/admin/providers',label:'模型供应商',icon:'users'},
  {to:'/admin/model-groups',label:'模型组',icon:'route'},
  {to:'/admin/users',label:'用户',icon:'users'},
  {to:'/admin/user-groups',label:'用户组',icon:'users'},
  {to:'/admin/smart-route',label:'智能路由',icon:'route'},
  {to:'/admin/compliance/words',label:'内容合规',icon:'shield'},
  {to:'/admin/usage',label:'用量统计',icon:'chart'},
  {to:'/admin/call-logs',label:'调用日志',icon:'file'},
  ...(auth.user?.role==='super_admin'&&operationsReady?[{to:'/admin/settings',label:'系统设置',icon:'settings'}]:[])
])
function active(to:string){return route.path.startsWith(to)||to==='/admin/compliance/words'&&route.path.startsWith('/admin/compliance/')}
const current=computed(()=>links.value.find(x=>active(x.to)))
const title=computed(()=>current.value?.label||({'/portal/profile':'个人设置','/admin/backups':'数据备份','/admin/audit-logs':'管理审计'} as Record<string,string>)[route.path]||'详情')
const section=computed(()=>({'/admin/smart-route/samples':'样本管理','/admin/smart-route/logs':'决策日志','/admin/smart-route/statistics':'统计','/admin/smart-route/configs':'路由规则','/admin/compliance/words':'词库','/admin/compliance/samples':'样本','/admin/compliance/policies':'策略','/admin/compliance/logs':'审核日志'} as Record<string,string>)[route.path]||'详情')
async function logout(){await auth.logout();await router.push('/login')}
function command(value:string){
  if(value==='logout')void logout()
  else void router.push(({'profile':'/portal/profile','portal':'/portal/models','admin':'/admin/dashboard','backups':'/admin/backups','audit':'/admin/audit-logs'} as Record<string,string>)[value]||'/portal/profile')
}
async function openAbout(){about.value=true;if(version.value)return;try{const response=await fetch('/openapi.json');if(response.ok)version.value=(await response.json()).info.version}catch{}}
</script>
<template>
<div v-if="['/login','/first-password'].includes(route.path)"><button class="public-theme icon-button" :aria-label="dark?'切换浅色主题':'切换深色主题'" @click="toggleTheme"><UiIcon :name="dark?'sun':'moon'"/></button><router-view/></div>
<div v-else class="shell reference-shell" :class="{collapsed}">
  <aside class="sidebar">
    <div class="brand"><img v-if="branding.logo" :src="branding.logo" alt="Logo" style="width:34px;height:34px;object-fit:contain"/><b v-else>HD</b><strong v-if="!collapsed" :title="branding.system_name">{{branding.system_name}}</strong></div>
    <nav aria-label="主导航"><el-tooltip v-for="link in links" :key="link.to" :content="link.label" placement="right" :disabled="!collapsed"><router-link :to="link.to" :class="{selected:active(link.to)}" :aria-label="link.label"><UiIcon :name="link.icon"/><span v-if="!collapsed">{{link.label}}</span></router-link></el-tooltip></nav>
    <div class="sidebar-account"><el-dropdown trigger="click" placement="top-start" @command="command"><button class="user-menu" aria-label="用户菜单"><UiIcon name="users"/><span v-if="!collapsed" class="account-name">{{auth.user?.name||auth.user?.username}}</span><span v-if="!collapsed">⌃</span></button><template #dropdown><el-dropdown-menu><el-dropdown-item v-if="auth.user?.role!=='user'" command="admin">管理后台</el-dropdown-item><el-dropdown-item command="portal">用户中心</el-dropdown-item><el-dropdown-item command="profile">修改密码 / 个人设置</el-dropdown-item><el-dropdown-item v-if="auth.user?.role==='super_admin'&&operationsReady" command="backups" divided>数据备份</el-dropdown-item><el-dropdown-item v-if="auth.user?.role!=='user'&&operationsReady" command="audit">管理审计</el-dropdown-item><el-dropdown-item command="logout" divided>退出登录</el-dropdown-item></el-dropdown-menu></template></el-dropdown></div>
  </aside>
  <div class="workspace"><header class="topbar"><div class="topbar-left"><button class="icon-button" :aria-label="collapsed?'展开侧栏':'收起侧栏'" @click="toggleSidebar"><UiIcon name="menu"/></button><span class="console-title">{{title}}</span><span v-if="current&&route.path!==current.to" class="muted">/ {{section}}</span></div><div class="topbar-right"><button class="console-top-link" @click="help=true">使用帮助</button><button class="console-top-link" @click="openAbout"><UiIcon name="help"/>关于</button><span class="console-language">简体中文</span><el-tooltip :content="dark?'浅色主题':'深色主题'"><button class="icon-button" :aria-label="dark?'切换浅色主题':'切换深色主题'" @click="toggleTheme"><UiIcon :name="dark?'sun':'moon'"/></button></el-tooltip></div></header><main :aria-busy="navigating"><div v-if="navigating" class="navigation-progress" role="progressbar" aria-label="正在打开页面"></div><router-view v-slot="{Component,route:viewRoute}"><Transition name="page" mode="out-in"><div :key="viewRoute.path" class="page-view"><component :is="Component"/></div></Transition></router-view></main></div>
</div>
<el-dialog v-model="about" title="关于" width="460px"><div class="about-brand"><img v-if="branding.logo" :src="branding.logo" alt="Logo"/><strong>{{branding.system_name}}</strong></div><p>当前版本：{{version?'v'+version:'暂未取得版本信息'}}</p><p>HeliData AI Gateway</p><el-button @click="about=false;help=true">使用帮助</el-button></el-dialog>
<el-dialog v-model="help" title="使用帮助" width="520px"><p>在模型广场查看已授权模型与接入说明，在 API Keys 创建访问凭据。网关用量以实际上报数据为准。</p><p>管理员可通过 Request ID 联查调用、路由和合规记录，检查账号健康与模型映射。</p><div class="toolbar"><el-button @click="help=false;router.push('/portal/models')">查看模型与接口说明</el-button></div></el-dialog>
</template>
