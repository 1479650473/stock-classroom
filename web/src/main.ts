import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './styles/tokens.css'
import './styles/base.css'
// 外观维度（密度/圆角/动效/背景）—— 在 tokens/base 之后载入，保证能覆盖默认值
import './styles/appearance.css'

createApp(App).use(createPinia()).use(router).mount('#app')
