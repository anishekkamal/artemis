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

/** A cron schedule as returned by `/api/schedules`. */
export interface Schedule {
  id: string;
  cron: string;
  goal: string;
  profile: string;
  device_serial: string | null;
  enabled: boolean;
  created_at: string;
  last_fired_minute: string | null;
  last_session_id: string | null;
  last_error: string | null;
  expected_output: string | null;
  enable_outputter: boolean | null;
  verification_level: string | null;
  explorer_mode: string | null;
  /** Local ISO minute of the next firing, or null when paused or never. */
  next_run: string | null;
}

/** Body of `POST /api/schedules`. */
export interface ScheduleCreate {
  cron: string;
  goal: string;
  profile: string;
  expected_output?: string;
  enable_outputter?: boolean;
  verification_level?: string;
  explorer_mode?: string;
}
