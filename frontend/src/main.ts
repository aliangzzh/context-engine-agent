import { createApp } from 'vue'
import App from './App.vue'
import { startRouter } from './router'
import './style.css'

startRouter() // 先按当前 hash 定位路由，再挂载
createApp(App).mount('#app')
