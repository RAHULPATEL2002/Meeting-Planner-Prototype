import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, tap } from 'rxjs';

import { AuthService } from './auth.service';
import { UserMe } from './models';

/** Profile and avatar operations for the signed-in user. */
@Injectable({ providedIn: 'root' })
export class UserService {
  private readonly http = inject(HttpClient);
  private readonly auth = inject(AuthService);

  updateProfile(patch: { full_name?: string; timezone?: string }): Observable<UserMe> {
    return this.http.patch<UserMe>('/api/users/me', patch).pipe(tap((u) => this.auth.setUser(u)));
  }

  /**
   * Uploads the avatar as multipart/form-data.
   *
   * Note there is no explicit Content-Type header: the browser must set it
   * itself so it can append the multipart boundary. Setting it by hand is the
   * classic way to break a file upload.
   */
  uploadAvatar(file: File): Observable<UserMe> {
    const form = new FormData();
    form.append('file', file);
    return this.http
      .post<UserMe>('/api/users/me/avatar', form)
      .pipe(tap((u) => this.auth.setUser(u)));
  }

  removeAvatar(): Observable<UserMe> {
    return this.http
      .delete<UserMe>('/api/users/me/avatar')
      .pipe(tap((u) => this.auth.setUser(u)));
  }
}
