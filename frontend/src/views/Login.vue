<script setup lang="ts">
import {ref} from 'vue'
import {branding} from '../ui/branding'
import {useRouter} from 'vue-router'
import {useAuth} from '../stores/auth'
import {message} from '../api/client'
const auth=useAuth(),router=useRouter(),username=ref(''),password=ref(''),loading=ref(false),error=ref('')
async function submit(){error.value='';if(!username.value||!password.value){error.value='请输入用户名和密码';return}loading.value=true;try{await auth.login(username.value,password.value);password.value='';await router.push(auth.user?.must_change_password?'/first-password':auth.user?.role==='user'?'/portal/models':'/admin/dashboard')}catch(e){error.value=message(e)}finally{loading.value=false}}
</script>
<template><div class="auth-page"><section class="auth-story"><div class="brand"><img v-if="branding.logo" :src="branding.logo" alt="Logo" style="width:40px;height:40px;object-fit:contain"/><b v-else>HD</b><strong>{{branding.system_name}}</strong></div><h1>统一接入<br>让模型服务有序运行</h1><p>HeliData AI Gateway<br>企业级大模型接入与管理平台</p></section><section class="auth-box"><div class="auth-form"><PageHeader title="登录工作台" description="使用您的本地账号登录"/><el-alert v-if="error" :title="error" type="error" :closable="false"/><el-form label-position="top" @submit.prevent="submit"><el-form-item label="用户名"><el-input v-model="username" placeholder="请输入用户名" autocomplete="username"/></el-form-item><el-form-item label="密码"><el-input v-model="password" type="password" show-password placeholder="请输入密码" autocomplete="current-password" @keyup.enter="submit"/></el-form-item><el-button type="primary" :loading="loading" @click="submit">登录</el-button></el-form><p class="muted" style="margin-top:24px">忘记密码请联系管理员。</p></div></section></div></template>
