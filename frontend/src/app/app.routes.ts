import { Routes } from '@angular/router';

import { authGuard, guestGuard } from './core/auth.guard';

/**
 * Every feature route is lazily loaded with `loadComponent`, so the login
 * screen — the only page an anonymous visitor sees — does not ship the meeting
 * pages in its bundle.
 */
export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'meetings' },
  {
    path: 'login',
    title: 'Sign in · Meeting Planner',
    canActivate: [guestGuard],
    loadComponent: () => import('./pages/login.component').then((m) => m.LoginComponent),
  },
  {
    path: 'register',
    title: 'Create an account · Meeting Planner',
    canActivate: [guestGuard],
    loadComponent: () => import('./pages/register.component').then((m) => m.RegisterComponent),
  },
  {
    path: 'profile',
    title: 'Your profile · Meeting Planner',
    canActivate: [authGuard],
    loadComponent: () => import('./pages/profile.component').then((m) => m.ProfileComponent),
  },
  {
    path: 'meetings',
    title: 'Meetings · Meeting Planner',
    canActivate: [authGuard],
    loadComponent: () =>
      import('./pages/meeting-list.component').then((m) => m.MeetingListComponent),
  },
  {
    path: 'meetings/new',
    title: 'New meeting · Meeting Planner',
    canActivate: [authGuard],
    loadComponent: () =>
      import('./pages/meeting-create.component').then((m) => m.MeetingCreateComponent),
  },
  {
    // Declared after 'meetings/new' so the literal segment wins over :id.
    path: 'meetings/:id',
    title: 'Meeting · Meeting Planner',
    canActivate: [authGuard],
    loadComponent: () =>
      import('./pages/meeting-detail.component').then((m) => m.MeetingDetailComponent),
  },
  { path: '**', redirectTo: 'meetings' },
];
