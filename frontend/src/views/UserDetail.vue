<script setup lang="ts">
import {formatDate} from '../ui/branding'
import {onMounted,ref} from 'vue'
import {useRoute} from 'vue-router'
import {api,message,type User} from '../api/client'
const route=useRoute(),user=ref<User|null>(null),error=ref(''),groupName=ref('未分配')
onMounted(async()=>{try{user.value=(await api.get('/admin/users/'+route.params.id)).data.data;if(user.value?.user_group_id)groupName.value=(await api.get('/admin/user-groups/'+user.value.user_group_id)).data.data.name}catch(e){error.value=message(e)}})
</script>
<template><div><el-button @click="$router.push('/admin/users')">返回用户列表</el-button><h1 style="margin-top:24px">用户详情</h1><router-link :to="{path:'/admin/call-logs',query:{user_id:String(route.params.id)}}"><el-button>查看调用日志</el-button></router-link><router-link :to="{path:'/admin/usage',query:{user_id:String(route.params.id)}}"><el-button>查看用量统计</el-button></router-link><el-alert v-if="error" :title="error" type="error"/><div class="panel" v-if="user"><el-descriptions :column="2" border><el-descriptions-item label="用户名">{{user.username}}</el-descriptions-item><el-descriptions-item label="姓名">{{user.name||'未填写'}}</el-descriptions-item><el-descriptions-item label="邮箱">{{user.email||'未填写'}}</el-descriptions-item><el-descriptions-item label="手机号">{{user.phone||'未填写'}}</el-descriptions-item><el-descriptions-item label="角色">{{user.role==='super_admin'?'超级管理员':user.role==='admin'?'管理员':'普通用户'}}</el-descriptions-item><el-descriptions-item label="状态">{{user.status==='enabled'?'启用':'禁用'}}</el-descriptions-item><el-descriptions-item label="密码状态">{{user.must_change_password?'首次登录待改密':'已完成改密'}}</el-descriptions-item><el-descriptions-item label="用户组">{{groupName}}</el-descriptions-item><el-descriptions-item label="创建时间">{{formatDate(user.created_at)}}</el-descriptions-item><el-descriptions-item label="最后登录">{{user.last_login_at?formatDate(user.last_login_at):'尚未登录'}}</el-descriptions-item></el-descriptions></div></div></template>

