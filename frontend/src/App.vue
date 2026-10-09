<script setup lang="ts">
import { onMounted } from 'vue'
import { api,ui,run } from './api'
import logo from './assets/logo.png'
onMounted(async()=>{await run(async()=>{ui.config=await api('/config');document.title=ui.config.brand.name},'');try{const state=await api('/session');ui.role=state.role;ui.caseIds=state.case_ids}catch{}})
</script>
<template>
<header class="site-header"><div class="brand-lockup"><RouterLink to="/" class="brand-mark" aria-label="助手首页"><img :src="logo" alt="" width="44" height="44"></RouterLink><div class="brand"><RouterLink to="/">{{ui.config.brand?.name??'生物实验智学助手'}}</RouterLink><span>{{ui.config.brand?.subtitle??'面向本科生物实验教学的知识探索与智能复盘工具'}}</span></div></div><nav aria-label="主导航"><RouterLink to="/">首页</RouterLink><RouterLink to="/knowledge">生物功能图谱</RouterLink><RouterLink to="/experiment">电泳异常分析</RouterLink><RouterLink to="/teacher">教师工作区</RouterLink></nav></header>
<main class="workspace"><div v-if="ui.message" :class="['notification',{error:ui.error}]" role="status"><span>{{ui.message}}</span><button class="quiet" @click="ui.message=''" aria-label="关闭提示">×</button></div><RouterView/></main>
<footer>面向实验课程的知识探索、证据记录与师生反馈 · AI 提供的观察和建议须经人工核对 <RouterLink to="/dev" class="developer-entry">开发调试</RouterLink></footer>
</template>
