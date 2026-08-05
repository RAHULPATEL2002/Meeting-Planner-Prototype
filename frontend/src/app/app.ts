import { Component, inject } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { AuthService } from './core/auth.service';
import { AvatarComponent } from './shared/avatar.component';

/**
 * Application shell: a top bar plus the routed page.
 *
 * On boot it re-validates any token restored from localStorage. If the token
 * has expired while the tab was closed, the HTTP interceptor sees the 401 and
 * redirects to /login — so the user never sees a half-loaded signed-in UI.
 */
@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, AvatarComponent],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App {
  private readonly auth = inject(AuthService);

  protected readonly user = this.auth.currentUser;
  protected readonly isAuthenticated = this.auth.isAuthenticated;

  constructor() {
    if (this.auth.isAuthenticated()) {
      this.auth.restoreSession().subscribe({
        // The interceptor already handles the redirect; swallow the error so it
        // does not surface as an unhandled rejection in the console.
        error: () => undefined,
      });
    }
  }

  protected signOut(): void {
    this.auth.logout();
  }
}
