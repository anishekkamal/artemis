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

import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Subject, of, throwError } from 'rxjs';
import { MacRoot } from '../../core/models/mac-access.model';
import { MacAccessService } from '../../services/mac-access.service';
import { MacFoldersComponent } from './mac-folders.component';

describe('MacFoldersComponent', () => {
  const roots = signal<MacRoot[]>([]);
  let svc: jasmine.SpyObj<MacAccessService> & { roots: typeof roots };

  function create() {
    const fixture = TestBed.createComponent(MacFoldersComponent);
    fixture.detectChanges();
    const el: HTMLElement = fixture.nativeElement;
    const button = (label: string) =>
      Array.from(el.querySelectorAll('button')).find((b) => b.textContent?.includes(label)) as HTMLButtonElement;
    return { fixture, el, button, cmp: fixture.componentInstance };
  }

  beforeEach(() => {
    roots.set([{ path: '/Users/me/Pictures', exists: true }]);
    svc = Object.assign(jasmine.createSpyObj('MacAccessService', ['list', 'add', 'replace', 'remove', 'pick']), {
      roots
    });
    svc.list.and.returnValue(of(roots()));
    TestBed.configureTestingModule({ providers: [{ provide: MacAccessService, useValue: svc }] });
  });

  it('lists shared folders and warns about a missing one', () => {
    roots.set([
      { path: '/Users/me/Pictures', exists: true },
      { path: '/Users/me/Gone', exists: false }
    ]);
    const { el } = create();
    expect(el.querySelectorAll('.folder-card').length).toBe(2);
    expect(el.querySelectorAll('.warn').length).toBe(1);
    expect(el.textContent).toContain('no longer exists');
  });

  it('Browse fills the add input without adding', () => {
    svc.pick.and.returnValue(of('/Users/me/Docs'));
    const { fixture, button, cmp } = create();
    button('Browse').click();
    fixture.detectChanges();
    expect(cmp.newPath()).toBe('/Users/me/Docs');
    expect(fixture.nativeElement.querySelector('input').value).toBe('/Users/me/Docs');
    expect(svc.add).not.toHaveBeenCalled();
  });

  it('keeps the input when the picker is cancelled and shows the wait note while open', () => {
    const open = new Subject<string | null>();
    svc.pick.and.returnValue(open);
    const { fixture, el, button, cmp } = create();
    cmp.newPath.set('/typed');
    button('Browse').click();
    fixture.detectChanges();
    expect(el.textContent).toContain('Waiting for folder picker on your Mac');
    open.next(null);
    fixture.detectChanges();
    expect(el.textContent).not.toContain('Waiting for folder picker');
    expect(cmp.newPath()).toBe('/typed');
  });

  it('Add posts the typed path, clears the input and shows API errors inline', () => {
    svc.add.and.returnValue(of([]));
    const { fixture, el, button, cmp } = create();
    cmp.newPath.set('  /Users/me/Docs ');
    fixture.detectChanges();
    button('Add').click();
    expect(svc.add).toHaveBeenCalledWith('/Users/me/Docs');
    expect(cmp.newPath()).toBe('');

    svc.add.and.returnValue(throwError(() => ({ error: { detail: 'Folder not found: /nope' } })));
    cmp.newPath.set('/nope');
    cmp.add();
    fixture.detectChanges();
    expect(el.querySelector('.error-banner')?.textContent).toContain('Folder not found: /nope');
    expect(cmp.newPath()).toBe('/nope');
  });

  it('Change opens the picker then replaces the folder', () => {
    svc.pick.and.returnValue(of('/Users/me/Other'));
    svc.replace.and.returnValue(of([]));
    const { button } = create();
    button('Change').click();
    expect(svc.replace).toHaveBeenCalledWith('/Users/me/Pictures', '/Users/me/Other');
  });

  it('Change does nothing when the picker is cancelled', () => {
    svc.pick.and.returnValue(of(null));
    const { button } = create();
    button('Change').click();
    expect(svc.replace).not.toHaveBeenCalled();
  });

  it('Remove asks for confirmation before deleting', () => {
    svc.remove.and.returnValue(of([]));
    const { fixture, button } = create();
    button('Remove').click();
    fixture.detectChanges();
    expect(svc.remove).not.toHaveBeenCalled();
    button('Remove').click();
    expect(svc.remove).toHaveBeenCalledWith('/Users/me/Pictures');
  });
});
