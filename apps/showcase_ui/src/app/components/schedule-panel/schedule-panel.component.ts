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

import { ChangeDetectionStrategy, Component, computed, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { concat, tap, toArray } from 'rxjs';
import { ScheduleService } from '../../services/schedule.service';
import { Schedule, ScheduleCreate } from '../../core/models/schedule.model';
import {
  RepeatMode,
  ScheduleSpec,
  buildCrons,
  describeCron,
  formatRunTime,
  summarizeSpec,
  validateSpec
} from '../../utils/schedule-cron.util';

/** Run options the composer would send to `/api/run`, minus goal and profile. */
export interface ScheduleRunOptions {
  expectedOutput?: string;
  enableOutputter?: boolean;
  verificationLevel?: string;
  explorerMode?: string;
}

@Component({
  selector: 'app-schedule-panel',
  imports: [FormsModule],
  templateUrl: './schedule-panel.component.html',
  styleUrl: './schedule-panel.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class SchedulePanelComponent {
  private schedules = inject(ScheduleService);

  goal = input.required<string>();
  profile = input.required<string>();
  options = input<ScheduleRunOptions>({});
  viewSchedules = output<void>();

  readonly repeatModes: { id: RepeatMode; label: string }[] = [
    { id: 'daily', label: 'Daily' },
    { id: 'weekdays', label: 'Weekdays' },
    { id: 'weekends', label: 'Weekends' },
    { id: 'custom', label: 'Custom days' },
    { id: 'interval', label: 'Every N minutes' }
  ];
  /** Monday first; `dow` is the cron day number. */
  readonly dayChips = [
    { dow: 1, label: 'Mon' },
    { dow: 2, label: 'Tue' },
    { dow: 3, label: 'Wed' },
    { dow: 4, label: 'Thu' },
    { dow: 5, label: 'Fri' },
    { dow: 6, label: 'Sat' },
    { dow: 0, label: 'Sun' }
  ];
  readonly formatRunTime = formatRunTime;

  repeat = signal<RepeatMode>('daily');
  days = signal<number[]>([1, 3, 5]);
  times = signal<string[]>(['09:00']);
  intervalMinutes = signal(30);
  limitHours = signal(false);
  fromHour = signal(9);
  toHour = signal(17);
  advancedOpen = signal(false);
  rawMode = signal(false);
  rawCron = signal('');

  saving = signal(false);
  error = signal<string | null>(null);
  created = signal<Schedule[]>([]);
  done = signal(false);

  spec = computed<ScheduleSpec>(() => ({
    repeat: this.repeat(),
    days: this.days(),
    times: this.times(),
    intervalMinutes: this.intervalMinutes(),
    fromHour: this.limitHours() ? this.fromHour() : null,
    toHour: this.limitHours() ? this.toHour() : null
  }));
  crons = computed(() => (this.rawMode() ? [this.rawCron().trim()].filter(Boolean) : buildCrons(this.spec())));
  problem = computed(() => {
    if (this.rawMode()) return this.crons().length ? null : 'Type a 5-field cron expression.';
    return validateSpec(this.spec());
  });
  summary = computed(() => {
    if (this.problem()) return '';
    if (!this.rawMode()) return summarizeSpec(this.spec());
    const cron = this.crons()[0];
    return describeCron(cron) ?? `Cron ${cron}`;
  });
  canSave = computed(() => !this.problem() && !!this.goal().trim() && !this.saving());

  setRepeat(mode: RepeatMode): void {
    this.repeat.set(mode);
  }

  toggleDay(dow: number): void {
    this.days.update((d) => (d.includes(dow) ? d.filter((x) => x !== dow) : [...d, dow]));
  }

  setTime(index: number, value: string): void {
    this.times.update((t) => t.map((x, i) => (i === index ? value : x)));
  }

  addTime(): void {
    this.times.update((t) => [...t, '12:00']);
  }

  removeTime(index: number): void {
    this.times.update((t) => t.filter((_, i) => i !== index));
  }

  toggleRaw(): void {
    if (!this.rawMode() && !this.rawCron()) {
      this.rawCron.set(this.crons()[0] ?? '');
    }
    this.rawMode.update((v) => !v);
  }

  save(): void {
    if (!this.canSave()) return;
    const o = this.options();
    const base: Omit<ScheduleCreate, 'cron'> = {
      goal: this.goal().trim(),
      profile: this.profile(),
      ...(o.expectedOutput?.trim() ? { expected_output: o.expectedOutput.trim() } : {}),
      ...(o.enableOutputter !== undefined ? { enable_outputter: o.enableOutputter } : {}),
      ...(o.verificationLevel ? { verification_level: o.verificationLevel } : {}),
      ...(o.explorerMode ? { explorer_mode: o.explorerMode } : {})
    };
    const crons = this.crons();
    const saved: Schedule[] = [];
    this.saving.set(true);
    this.error.set(null);
    // One at a time: a rejected cron stops the rest instead of half-creating the set.
    concat(
      ...crons.map((cron) =>
        this.schedules.create({ ...base, cron }).pipe(tap((s) => saved.push(s)))
      )
    )
      .pipe(toArray())
      .subscribe({
        next: () => {
          this.created.set(saved);
          this.done.set(true);
          this.saving.set(false);
        },
        error: (err) => {
          const detail = err?.error?.detail;
          const msg = typeof detail === 'string' ? detail : 'Could not save the schedule. Check the server connection.';
          this.error.set(saved.length ? `${msg} (${saved.length} of ${crons.length} saved.)` : msg);
          this.saving.set(false);
        }
      });
  }

  scheduleAnother(): void {
    this.done.set(false);
    this.created.set([]);
  }
}
