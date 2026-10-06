<script setup lang="ts">
import {ref} from 'vue'
import {useRouter} from 'vue-router'
import {ElMessage} from 'element-plus'
import {api,message} from '../api/client'
import {useAuth} from '../stores/auth'
const oldPassword=ref(''),newPassword=ref(''),confirm=ref(''),error=ref(''),loading=ref(false),router=useRouter(),auth=useAuth()
async function submit(){error.value='';if(newPassword.value!==confirm.value){error.value='两次输入的新密码不一致';return}loading.value=true;try{await api.post('/auth/change-password',{old_password:oldPassword.value,new_password:newPassword.value});auth.clear();ElMessage.success('密码已修改，请重新登录');await router.push('/login')}catch(e){error.value=message(e)}finally{loading.value=false}}
</script>
<template><div class="auth-box" style="min-height:100vh"><div class="auth-form"><PageHeader title="首次修改密码" description="为保护账号，请替换管理员分配的临时密码。"/><el-alert v-if="error" :title="error" type="error" :closable="false"/><el-form label-position="top"><el-form-item label="原密码"><el-input v-model="oldPassword" type="password" show-password autocomplete="current-password"/></el-form-item><el-form-item label="新密码"><el-input v-model="newPassword" type="password" show-password autocomplete="new-password"/></el-form-item><p class="muted">至少12位，包含大小写字母、数字、符号中的三类。</p><el-form-item label="确认新密码"><el-input v-model="confirm" type="password" show-password autocomplete="new-password"/></el-form-item><el-button type="primary" :loading="loading" @click="submit">修改密码并重新登录</el-button></el-form></div></div></template>
