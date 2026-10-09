import { createApp } from 'vue'
import { createRouter,createWebHistory } from 'vue-router'
import App from './App.vue'
import Knowledge from './Knowledge.vue'
import Experiment from './Experiment.vue'
import Teacher from './Teacher.vue'
import Home from './Home.vue'
import './style.css'
const router=createRouter({history:createWebHistory(),routes:[{path:'/',component:Home},{path:'/tasks/:code?',component:Home},{path:'/knowledge/:id?',component:Knowledge},{path:'/experiment',component:Experiment},{path:'/cases/:id',component:Experiment},{path:'/teacher',component:Teacher},{path:'/:pathMatch(.*)*',redirect:'/'}]})
createApp(App).use(router).mount('#app')
