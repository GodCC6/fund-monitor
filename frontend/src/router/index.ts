import { createRouter, createWebHistory } from 'vue-router'
import Home from '../views/Home.vue'
import PortfolioDetail from '../views/PortfolioDetail.vue'
import FundDetail from '../views/FundDetail.vue'
import FundCompare from '../views/FundCompare.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'Home', component: Home },
    { path: '/portfolio/:id', name: 'PortfolioDetail', component: PortfolioDetail },
    { path: '/fund/:code', name: 'FundDetail', component: FundDetail },
    { path: '/compare', name: 'FundCompare', component: FundCompare },
  ],
})

export default router
