import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { CronPanel } from './CronPanel'
import type { DeliveryTargetMap } from './logic'

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() },
}))

const TARGETS: DeliveryTargetMap = {
  telegram: [
    { id: '1245463966', label: 'AndreaPN | 404AI Labs (@andreapn_dackielabs)', kind: 'dm' },
    { id: '-1001234567890', label: '-1001234567890', kind: 'group' },
  ],
}

function renderPanel(deliveryTargets: DeliveryTargetMap = TARGETS) {
  return render(
    <CronPanel
      job={null}
      template={null}
      activeSessionKey="agent:main:webchat:abc"
      saving={false}
      deliveryTargets={deliveryTargets}
      onCancel={() => undefined}
      onSubmit={() => undefined}
    />,
  )
}

/** Open Advanced delivery, pick "Announce to channel", and name the channel. */
function openAnnounceFor(channel: string) {
  fireEvent.click(screen.getByText('Advanced delivery & wake'))
  fireEvent.change(screen.getByLabelText('Delivery mode'), { target: { value: 'announce' } })
  fireEvent.change(screen.getByLabelText('Channel'), { target: { value: channel } })
}

describe('CronPanel recipient field', () => {
  it('offers the paired chats for a channel we know', () => {
    // The bug this replaces: a free-text box accepted a session key, and the
    // job only failed at delivery time, ten minutes later.
    renderPanel()
    openAnnounceFor('telegram')

    const recipient = screen.getByLabelText('Recipient')
    expect(recipient.tagName).toBe('SELECT')
    expect(
      within(recipient).getByRole('option', {
        name: 'AndreaPN | 404AI Labs (@andreapn_dackielabs)',
      }),
    ).toHaveValue('1245463966')
  })

  it('selecting a chat puts its id — not its label — in the form', () => {
    renderPanel()
    openAnnounceFor('telegram')

    fireEvent.change(screen.getByLabelText('Recipient'), { target: { value: '1245463966' } })

    expect(screen.getByLabelText('Recipient')).toHaveValue('1245463966')
  })

  it('keeps a way to type an id the list does not have', () => {
    // A group chat that is not in group_chat_ids must still be reachable.
    renderPanel()
    openAnnounceFor('telegram')

    fireEvent.change(screen.getByLabelText('Recipient'), { target: { value: '__manual__' } })

    const manual = screen.getByLabelText('Recipient')
    expect(manual.tagName).toBe('INPUT')
    fireEvent.change(manual, { target: { value: '-1009999' } })
    expect(screen.getByLabelText('Recipient')).toHaveValue('-1009999')
  })

  it('falls back to a text box for a channel with no known recipients', () => {
    renderPanel()
    openAnnounceFor('slack')

    expect(screen.getByLabelText('Recipient').tagName).toBe('INPUT')
  })

  it('falls back to a text box when the gateway reported no targets at all', () => {
    renderPanel({})
    openAnnounceFor('telegram')

    expect(screen.getByLabelText('Recipient').tagName).toBe('INPUT')
  })
})
