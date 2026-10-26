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

import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { Observable } from 'rxjs';
import { MacAccessService } from '../../services/mac-access.service';
import { MacRoot } from '../../core/models/mac-access.model';

/** Which picker is open: 'add' for the add row, or the path of the folder being changed. */
type PickerTarget = 'add' | string;

@Component({
  selector: 'app-mac-folders',
  templateUrl: './mac-folders.component.html',
  styleUrl: './mac-folders.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class MacFoldersComponent {
  private macAccess = inject(MacAccessService);

  roots = this.macAccess.roots;
  loaded = signal(false);
  error = signal<string | null>(null);
  newPath = signal('');
  picking = signal<PickerTarget | null>(null);
  busy = signal(false);
  confirmRemovePath = signal<string | null>(null);

  constructor() {
    this.macAccess.list().subscribe({
      next: () => this.loaded.set(true),
      error: () => {
        this.loaded.set(true);
        this.error.set('Could not load the shared folders. Check the server connection.');
      }
    });
  }

  browseForNew(): void {
    this.pick('add', (path) => this.newPath.set(path));
  }

  change(root: MacRoot): void {
    this.pick(root.path, (path) => this.run(this.macAccess.replace(root.path, path)));
  }

  add(): void {
    const path = this.newPath().trim();
    if (!path) return;
    this.run(this.macAccess.add(path), () => this.newPath.set(''));
  }

  remove(root: MacRoot): void {
    this.confirmRemovePath.set(null);
    this.run(this.macAccess.remove(root.path));
  }

  private pick(target: PickerTarget, onPicked: (path: string) => void): void {
    this.error.set(null);
    this.picking.set(target);
    this.macAccess.pick().subscribe({
      next: (path) => {
        this.picking.set(null);
        if (path) onPicked(path);
      },
      error: (err) => {
        this.picking.set(null);
        this.error.set(err?.error?.detail || 'The folder picker did not open. Type the path instead.');
      }
    });
  }

  private run(req: Observable<unknown>, after?: () => void): void {
    this.busy.set(true);
    this.error.set(null);
    req.subscribe({
      next: () => {
        this.busy.set(false);
        after?.();
      },
      error: (err) => {
        this.busy.set(false);
        this.error.set(err?.error?.detail || 'That did not work. Please check server connection.');
      }
    });
  }
}
