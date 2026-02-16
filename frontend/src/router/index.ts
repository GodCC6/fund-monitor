import { createRouter, createWebHistory } from 'vue-router'
import Home from '../views/Home.vue'
import PortfolioDetail from '../views/PortfolioDetail.vue'
import FundDetail from '../views/FundDetail.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'Home', component: Home },
    { path: '/portfolio/:id', name: 'PortfolioDetail', component: PortfolioDetail },
    { path: '/fund/:code', name: 'FundDetail', component: FundDetail },
  ],
})

export default router
