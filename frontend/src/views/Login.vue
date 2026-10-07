<script setup lang="ts">
import {onMounted,ref} from 'vue'
import {branding} from '../ui/branding'
import {dark} from '../ui/preferences'
import {useRouter} from 'vue-router'
import {useAuth} from '../stores/auth'
import {message} from '../api/client'
const auth=useAuth(),router=useRouter(),username=ref(''),password=ref(''),loading=ref(false),error=ref('')
const help=ref(false),forgot=ref(false),about=ref(false),version=ref(''),year=new Date().getFullYear()
onMounted(async()=>{try{const response=await fetch('/openapi.json');if(response.ok)version.value=(await response.json()).info.version}catch{}})
async function submit(){
  if(loading.value)return
  error.value=''
  if(!username.value||!password.value){error.value='请输入用户名和密码';return}
  loading.value=true
  try{await auth.login(username.value,password.value);password.value='';await router.push(auth.user?.must_change_password?'/first-password':auth.user?.role==='user'?'/portal/models':'/admin/dashboard')}
  catch(e){error.value=message(e)}finally{loading.value=false}
}
</script>
<template>
  <div class="login-page" :class="{'login-dark':dark}">
    <span class="login-language" aria-label="当前语言">简体中文</span>
    <main class="login-main">
      <section class="login-card" aria-labelledby="login-title">
        <h1 id="login-title" class="login-title"><span>登录</span><strong>{{branding.system_name}}</strong></h1>
        <el-alert v-if="error" :title="error" type="error" :closable="false" role="alert"/>
        <el-form class="login-form" label-position="top" @submit.prevent="submit">
          <el-form-item label="用户名"><el-input v-model="username" aria-label="用户名" placeholder="请输入用户名" autocomplete="username" :disabled="loading" autofocus><template #prefix><UiIcon name="user"/></template></el-input></el-form-item>
          <el-form-item label="密码"><el-input v-model="password" aria-label="密码" type="password" show-password placeholder="请输入密码" autocomplete="current-password" :disabled="loading"><template #prefix><UiIcon name="lock"/></template></el-input></el-form-item>
          <div class="login-forgot"><button type="button" class="login-link" @click="forgot=true">忘记密码？</button></div>
          <el-button class="login-submit" type="primary" native-type="submit" :loading="loading"><UiIcon v-if="!loading" name="login"/><span>登录</span></el-button>
        </el-form>
      </section>
    </main>
    <footer class="login-footer"><span>© {{year}} 合力数据</span><span class="login-separator" aria-hidden="true"></span><button type="button" class="login-link" @click="help=true">帮助</button><template v-if="version"><span class="login-separator" aria-hidden="true"></span><button type="button" class="login-link" @click="about=true">v{{version}}</button></template></footer>
    <el-dialog v-model="forgot" title="忘记密码" width="400px"><p>请联系系统管理员重置密码。重置后，使用管理员提供的临时密码登录，并按提示设置新密码。</p><template #footer><el-button type="primary" @click="forgot=false">知道了</el-button></template></el-dialog>
    <el-dialog v-model="help" title="登录帮助" width="440px"><p>使用管理员分配的用户名和密码登录 {{branding.system_name}}。</p><p>首次登录需要修改临时密码。若账号被禁用或无法登录，请联系系统管理员。</p><template #footer><el-button @click="help=false">关闭</el-button></template></el-dialog>
    <el-dialog v-model="about" title="关于" width="400px"><p>{{branding.system_name}}</p><p>HeliData AI Gateway</p><p>当前版本：v{{version}}</p></el-dialog>
  </div>
</template>
<style scoped>
.login-page{min-height:100vh;min-height:100dvh;display:flex;flex-direction:column;background:linear-gradient(180deg,#dceafb 0%,#e9f1fa 60%,#f7f9fc 100%)}
.login-language{position:absolute;right:66px;top:24px;font-size:13px;color:var(--muted)}
.login-main{flex:1;display:flex;align-items:center;justify-content:center;padding:76px 24px 48px}
.login-card{width:400px;max-width:100%;padding:40px;background:var(--surface);border:1px solid rgba(255,255,255,.65);border-radius:12px;box-shadow:0 5px 18px rgba(25,45,70,.12)}
.login-title{display:flex;align-items:center;justify-content:center;gap:10px;margin:0 0 34px;font-size:20px;line-height:1.4;font-weight:400}
.login-title strong{font-size:18px;font-weight:600;color:var(--el-color-primary);overflow-wrap:anywhere;min-width:0}
.login-form :deep(.el-form-item){margin-bottom:22px}
.login-form :deep(.el-form-item__label){font-size:14px;color:var(--text);padding-bottom:7px;line-height:22px}
.login-form :deep(.el-input__wrapper){min-height:44px;padding:1px 12px;border-radius:6px}
.login-form :deep(.el-input__prefix){color:var(--muted)}
.login-form .ui-icon{width:16px;height:16px}
.login-form :deep(.el-form-item:nth-child(2)){margin-bottom:0}
.login-forgot{display:flex;justify-content:flex-end;margin:7px 0 20px}
.login-link{padding:0;border:0;background:transparent;color:var(--el-color-primary);font-size:13px;line-height:20px;cursor:pointer}
.login-link:hover{text-decoration:underline}
.login-link:focus-visible{outline:2px solid var(--el-color-primary);outline-offset:4px;border-radius:2px}
.login-submit{width:100%;height:44px;border-radius:6px;font-size:14px}
.login-submit :deep(span){display:inline-flex;align-items:center;justify-content:center;gap:8px}
.login-footer{display:flex;justify-content:center;align-items:center;gap:16px;flex-wrap:wrap;padding:20px 24px 24px;color:var(--muted);font-size:13px;line-height:20px}
.login-separator{width:1px;height:12px;background:var(--line)}
.login-page.login-dark{background:linear-gradient(180deg,#152d4c 0%,#17263d 60%,#111b2a 100%)}
.login-dark .login-card{border-color:var(--line);box-shadow:0 5px 24px rgba(0,0,0,.25)}
@media(max-width:480px){.login-main{padding:72px 20px 32px}.login-card{padding:32px 24px}.login-title{gap:8px}.login-title strong{font-size:16px}.login-footer{gap:12px;padding-bottom:20px}}
</style>
