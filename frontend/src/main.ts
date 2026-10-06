import {createApp} from 'vue'
import {createPinia} from 'pinia'
import {createRouter,createWebHistory} from 'vue-router'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import './styles/console.css'
import PageHeader from './components/PageHeader.vue'
import EmptyState from './components/EmptyState.vue'
import UiIcon from './components/UiIcon.vue'
import App from './App.vue'
const Login=()=>import('./views/Login.vue')
const Password=()=>import('./views/Password.vue')
const Users=()=>import('./views/Users.vue')
const Groups=()=>import('./views/Groups.vue')
const ModelGroups=()=>import('./views/ModelGroups.vue')
const SmartRoute=()=>import('./views/SmartRoute.vue')
const Compliance=()=>import('./views/Compliance.vue')
const Settings=()=>import('./views/Settings.vue')
const SystemOperations=()=>import('./views/SystemOperations.vue')
const Providers=()=>import('./views/Providers.vue')
const ProviderDetail=()=>import('./views/ProviderDetail.vue')
const Keys=()=>import('./views/Keys.vue')
const Profile=()=>import('./views/Profile.vue')
const UserDetail=()=>import('./views/UserDetail.vue')
const Portal=()=>import('./views/Portal.vue')
const Health=()=>import('./Health.vue')
const Dashboard=()=>import('./views/Dashboard.vue')
const Usage=()=>import('./views/Usage.vue')
const CallLogs=()=>import('./views/CallLogs.vue')
const CallLogDetail=()=>import('./views/CallLogDetail.vue')
import {useAuth} from './stores/auth'
const pinia=createPinia()
const router=createRouter({history:createWebHistory(),routes:[
  {path:'/',redirect:'/admin/dashboard'},
  {path:'/login',component:Login},
  {path:'/first-password',component:Password},
  {path:'/admin/dashboard',component:Dashboard,meta:{admin:true}},
  {path:'/admin/settings',component:Settings,meta:{superAdmin:true}},
  {path:'/admin/backups',component:SystemOperations,meta:{superAdmin:true}},
  {path:'/admin/audit-logs',component:SystemOperations,meta:{admin:true}},
  ...['words','samples','policies','logs'].map(view=>({path:'/admin/compliance/'+view,component:Compliance,meta:{admin:true}})),
  {path:'/admin/users',component:Users,meta:{admin:true}},
  {path:'/admin/users/:id',component:UserDetail,meta:{admin:true}},
  {path:'/admin/user-groups',component:Groups,meta:{admin:true}},
  {path:'/admin/model-groups',component:ModelGroups,meta:{admin:true}},
  {path:'/admin/smart-route',redirect:'/admin/smart-route/samples'},
  ...['/admin/smart-route/configs','/admin/smart-route/samples','/admin/smart-route/logs','/admin/smart-route/statistics'].map(path=>({path,component:SmartRoute,meta:{admin:true}})),
  {path:'/admin/providers',component:Providers,meta:{admin:true}},
  {path:'/admin/providers/:id',component:ProviderDetail,meta:{admin:true}},
  {path:'/admin/usage',component:Usage,meta:{admin:true}},
  {path:'/portal/usage',component:Usage},
  {path:'/admin/call-logs',component:CallLogs,meta:{admin:true}},
  {path:'/admin/call-logs/:requestId',component:CallLogDetail,meta:{admin:true}},
  {path:'/portal/api-keys',component:Keys},
  {path:'/portal/profile',component:Profile},
  {path:'/portal/models',component:Portal},
  {path:'/health-status',component:Health},
  {path:'/:pathMatch(.*)*',redirect:'/'}
]})
router.beforeEach(async to=>{
  const auth=useAuth(pinia);await auth.init()
  if(to.path==='/health-status')return true
  if(!auth.user)return to.path==='/login'?true:'/login'
  if(auth.user.must_change_password)return to.path==='/first-password'?true:'/first-password'
  if(to.path==='/login'||to.path==='/first-password')return auth.user.role==='user'?'/portal/models':'/admin/dashboard'
  if(to.meta.admin&&auth.user.role==='user')return'/portal/models'
  if(to.meta.superAdmin&&auth.user.role!=='super_admin')return auth.user.role==='user'?'/portal/models':'/admin/dashboard'
  return true
})
createApp(App).component('PageHeader',PageHeader).component('EmptyState',EmptyState).component('UiIcon',UiIcon).use(pinia).use(router).use(ElementPlus,{locale:zhCn}).mount('#app')




