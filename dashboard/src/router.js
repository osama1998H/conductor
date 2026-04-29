import { createRouter, createWebHashHistory } from "vue-router";

const routes = [
  { path: "/", redirect: "/overview" },
  { path: "/overview", component: () => import("./pages/OverviewPage.vue") },
  { path: "/feed",     component: () => import("./pages/FeedPage.vue") },
  { path: "/jobs/:job_id?",       component: () => import("./pages/JobsPage.vue"),      props: true },
  { path: "/dlq/:entry_name?",    component: () => import("./pages/DlqPage.vue"),       props: true },
  { path: "/schedules/:name?",    component: () => import("./pages/SchedulesPage.vue"), props: true },
  { path: "/workers/:worker_id?", component: () => import("./pages/WorkersPage.vue"),   props: true },
  { path: "/workflows", component: () => import("./pages/WorkflowsPage.vue") },
  { path: "/workflows/runs/:run_id", component: () => import("./pages/WorkflowRunDetailPage.vue") },
];

export default createRouter({ history: createWebHashHistory(), routes });
