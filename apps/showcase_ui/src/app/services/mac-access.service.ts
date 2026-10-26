/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import { Injectable, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, map, switchMap, tap } from 'rxjs';
import { MacRoot } from '../core/models/mac-access.model';

@Injectable({ providedIn: 'root' })
export class MacAccessService {
  private http = inject(HttpClient);

  /** Last list fetched, shared by the tab badge and the folders view. */
  readonly roots = signal<MacRoot[]>([]);

  list(): Observable<MacRoot[]> {
    return this.http.get<{ roots: MacRoot[] }>('/api/mac-access').pipe(
      map((r) => r.roots),
      tap((roots) => this.roots.set(roots))
    );
  }

  add(path: string): Observable<MacRoot[]> {
    return this.http.post('/api/mac-access', { path }).pipe(switchMap(() => this.list()));
  }

  replace(oldPath: string, newPath: string): Observable<MacRoot[]> {
    return this.http
      .put('/api/mac-access', { old_path: oldPath, new_path: newPath })
      .pipe(switchMap(() => this.list()));
  }

  remove(path: string): Observable<MacRoot[]> {
    return this.http.delete('/api/mac-access', { params: { path } }).pipe(switchMap(() => this.list()));
  }

  /** Opens the folder chooser on the Mac; emits null when the user cancels. */
  pick(): Observable<string | null> {
    return this.http.post<{ path: string | null }>('/api/mac-access/pick', {}).pipe(map((r) => r.path));
  }
}
