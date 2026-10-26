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

import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { MacAccessService } from './mac-access.service';

describe('MacAccessService', () => {
  let service: MacAccessService;
  let http: HttpTestingController;
  const roots = [{ path: '/Users/me/Pictures', exists: true }];

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [MacAccessService, provideHttpClient(withXhr()), provideHttpClientTesting()]
    });
    service = TestBed.inject(MacAccessService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('stores the listed roots', () => {
    service.list().subscribe();
    http.expectOne('/api/mac-access').flush({ roots });
    expect(service.roots()).toEqual(roots);
  });

  it('refreshes the list after adding', () => {
    service.add('/Users/me/Pictures').subscribe();
    const post = http.expectOne('/api/mac-access');
    expect(post.request.method).toBe('POST');
    expect(post.request.body).toEqual({ path: '/Users/me/Pictures' });
    post.flush({ path: '/Users/me/Pictures' });
    http.expectOne('/api/mac-access').flush({ roots });
    expect(service.roots()).toEqual(roots);
  });

  it('replaces with old_path and new_path', () => {
    service.replace('/a', '/b').subscribe();
    const put = http.expectOne('/api/mac-access');
    expect(put.request.method).toBe('PUT');
    expect(put.request.body).toEqual({ old_path: '/a', new_path: '/b' });
    put.flush({ path: '/b' });
    http.expectOne('/api/mac-access').flush({ roots: [] });
  });

  it('removes by query parameter', () => {
    service.remove('/a b').subscribe();
    const del = http.expectOne((r) => r.url === '/api/mac-access' && r.method === 'DELETE');
    expect(del.request.params.get('path')).toBe('/a b');
    del.flush({ status: 'removed' });
    http.expectOne('/api/mac-access').flush({ roots: [] });
    expect(service.roots()).toEqual([]);
  });

  it('returns the picked path, or null on cancel', () => {
    let picked: string | null = 'unset';
    service.pick().subscribe((p) => (picked = p));
    http.expectOne('/api/mac-access/pick').flush({ path: '/Users/me/Docs' });
    expect(picked).toBe('/Users/me/Docs');

    service.pick().subscribe((p) => (picked = p));
    http.expectOne('/api/mac-access/pick').flush({ path: null });
    expect(picked).toBeNull();
  });
});
