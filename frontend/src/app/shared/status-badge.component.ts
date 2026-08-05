import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { ParticipantStatus } from '../core/models';

const LABELS: Record<ParticipantStatus, string> = {
  invited: 'Awaiting reply',
  accepted: 'Going',
  declined: 'Not going',
  tentative: 'Maybe',
};

/** Colour-coded RSVP pill. Text carries the meaning; colour only reinforces it. */
@Component({
  selector: 'app-status-badge',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<span class="badge" [class]="'badge--' + status()">{{ label() }}</span>`,
  styles: [
    `
      .badge {
        display: inline-block;
        padding: 0.15rem 0.55rem;
        border-radius: 999px;
        font-size: 0.75rem;
        font-weight: 600;
        white-space: nowrap;
        border: 1px solid transparent;
      }
      .badge--accepted {
        background: #e6f6ec;
        color: #14713a;
        border-color: #b7e2c6;
      }
      .badge--declined {
        background: #fdeaea;
        color: #a31212;
        border-color: #f5c2c2;
      }
      .badge--tentative {
        background: #fff5e0;
        color: #8a5a00;
        border-color: #f2dca6;
      }
      .badge--invited {
        background: #eef1f6;
        color: #4a5568;
        border-color: #d6dce7;
      }
    `,
  ],
})
export class StatusBadgeComponent {
  readonly status = input.required<ParticipantStatus>();
  protected readonly label = computed(() => LABELS[this.status()]);
}
