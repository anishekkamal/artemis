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

import { ChangeDetectionStrategy, Component, inject, input, output, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router } from '@angular/router';
import { timer } from 'rxjs';
import { AgentService } from '../../services/agent.service';
import { ScheduleService } from '../../services/schedule.service';
import { Schedule } from '../../core/models/schedule.model';
import { describeCron, formatRunTime } from '../../utils/schedule-cron.util';

const REFRESH_MS = 30_000;

@Component({
  selector: 'app-scheduled-tasks',
  templateUrl: './scheduled-tasks.component.html',
  styleUrl: './scheduled-tasks.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class ScheduledTasksComponent {
  private schedules = inject(ScheduleService);
  private agent = inject(AgentService);
  private router = inject(Router);

  /** Same gate as the composer's Run button. */
  isReady = input.required<boolean>();
  openComposer = output<void>();

  items = this.schedules.items;
  loaded = signal(false);
  actionError = signal<string | null>(null);
  busyId = signal<string | null>(null);
  confirmDeleteId = signal<string | null>(null);
  readonly formatRunTime = formatRunTime;
  readonly describe = (s: Schedule): string => describeCron(s.cron) ?? s.cron;

  constructor() {
    // Created with the tab and destroyed when it closes, so this polls only while open.
    timer(0, REFRESH_MS)
      .pipe(takeUntilDestroyed())
      .subscribe(() =>
        this.schedules.list().subscribe({
          next: () => {
            this.loaded.set(true);
          },
          error: () => {
            this.loaded.set(true);
            this.actionError.set('Could not load schedules. Check the server connection.');
          }
        })
      );
  }

  toggle(s: Schedule): void {
    this.act(s.id, this.schedules.setEnabled(s.id, !s.enabled));
  }

  remove(s: Schedule): void {
    this.confirmDeleteId.set(null);
    this.act(s.id, this.schedules.remove(s.id));
  }

  runNow(s: Schedule): void {
    if (!this.isReady()) return;
    const pro = s.profile === 'pro';
    this.busyId.set(s.id);
    this.actionError.set(null);
    this.agent
      .runTask(
        s.goal,
        s.profile,
        pro && s.expected_output ? s.expected_output : undefined,
        pro && s.enable_outputter !== null ? s.enable_outputter : undefined,
        pro && (s.verification_level || s.explorer_mode)
          ? {
              verificationLevel: s.verification_level ?? undefined,
              explorerMode: s.explorer_mode ?? undefined
            }
          : undefined
      )
      .subscribe({
        next: () => {
          this.busyId.set(null);
          this.router.navigate(['/workspace']);
        },
        error: (err) => {
          this.busyId.set(null);
          this.actionError.set(err?.error?.detail || 'Failed to start the task. Please check server connection.');
        }
      });
  }

  private act(id: string, req: ReturnType<ScheduleService['remove']>): void {
    this.busyId.set(id);
    this.actionError.set(null);
    req.subscribe({
      next: () => this.busyId.set(null),
      error: (err) => {
        this.busyId.set(null);
        this.actionError.set(err?.error?.detail || 'That did not work. Please check server connection.');
      }
    });
  }
}
