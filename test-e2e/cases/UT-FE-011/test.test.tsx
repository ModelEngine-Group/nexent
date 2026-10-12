import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import GroupList from '@/app/[locale]/resource-manage/components/resources/GroupList';
import InvitationList from '@/app/[locale]/resource-manage/components/resources/InvitationList';

const fx = vi.hoisted(() => ({
  t: (key: string) => key,
  users: [{ id: 'alice', username: 'Alice' }, { id: 'bob', username: 'Bob' }],
  groups: [{ group_id: 31, group_name: 'Group A', group_description: 'Fixture group', user_count: 1 }],
  refetchUsers: vi.fn(), refetchInvites: vi.fn(),
  members: vi.fn(), updateGroup: vi.fn(), updateMembers: vi.fn(),
  createInvitation: vi.fn(), exists: vi.fn(), defaultGroup: vi.fn(),
  invitations: [{ invitation_id: 41, invitation_code: 'OLD-CODE', code_type: 'USER_INVITE',
    status: 'EXPIRE', capacity: 1, used_times: 0, expiry_date: '2020-01-01', group_ids: [31] }],
}));
vi.mock('react-i18next', async original => ({
  ...await original<typeof import('react-i18next')>(), useTranslation: () => ({ t: fx.t }),
}));
vi.mock('@/hooks/group/useGroupList', () => ({
  useGroupList: () => ({ data: { groups: fx.groups, total: 1 }, isLoading: false, refetch: vi.fn() }),
}));
vi.mock('@/hooks/user/useUserList', () => ({
  useUserList: () => ({ data: { users: fx.users }, refetch: fx.refetchUsers }),
}));
vi.mock('@/hooks/invitation/useInvitationList', () => ({
  useInvitationList: () => ({ data: { items: fx.invitations, total: 1 }, isLoading: false, refetch: fx.refetchInvites }),
}));
vi.mock('@/hooks/useConfirmModal', () => ({ useConfirmModal: () => ({ confirm: vi.fn() }) }));
vi.mock('@/components/providers/AuthorizationProvider', () => ({
  useAuthorizationContext: () => ({ user: { role: 'ADMIN', tenantId: 'component-tenant' } }),
}));
vi.mock('@/services/groupService', () => ({
  getGroupMembers: fx.members, updateGroup: fx.updateGroup, updateGroupMembers: fx.updateMembers,
  getTenantDefaultGroupId: fx.defaultGroup,
  createGroup: vi.fn(), deleteGroup: vi.fn(), addUserToGroup: vi.fn(), removeUserFromGroup: vi.fn(),
}));
vi.mock('@/services/invitationService', () => ({
  createInvitation: fx.createInvitation, checkInvitationCodeExists: fx.exists,
  updateInvitation: vi.fn(), deleteInvitation: vi.fn(),
}));
let client: QueryClient;
beforeEach(() => {
  // JSDOM has no pseudo-element layout; these tests assert form behavior.
  const computed = window.getComputedStyle.bind(window);
  vi.spyOn(window, 'getComputedStyle').mockImplementation(element => computed(element));
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  fx.members.mockResolvedValue([fx.users[0]]);
  fx.updateGroup.mockResolvedValue({});
  fx.updateMembers.mockResolvedValue({ added_count: 1, removed_count: 0, total_members: 2 });
  fx.defaultGroup.mockResolvedValue(31);
  fx.exists.mockResolvedValue(false);
  fx.createInvitation.mockResolvedValue({ invitation_id: 42 });
});
afterEach(async () => {
  cleanup(); client.clear();
  // Flush Ant Design's deferred state while the browser environment is alive.
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 120)); });
  vi.restoreAllMocks();
});
function renderGroups() {
  render(<QueryClientProvider client={client}><GroupList tenantId="component-tenant" /></QueryClientProvider>);
}
async function openInvite() {
  render(<InvitationList tenantId="component-tenant" />);
  await userEvent.click(screen.getByRole('button', { name: 'tenantResources.invitation.createInvitation' }));
  return screen.findByRole('dialog');
}
describe('UT-FE-011 actual group and invitation forms', () => {
  it('selected members are submitted as one exact batch and user queries refresh', async () => {
    renderGroups();
    const row = screen.getByText('Group A').closest('tr')!;
    await userEvent.click(within(row).getAllByRole('button')[1]);
    const dialog = await screen.findByRole('dialog');
    const selector = within(dialog).getByRole('combobox', { name: 'tenantResources.groups.members' });
    fireEvent.mouseDown(selector);
    const option = await screen.findByText('Bob', { selector: '.ant-select-item-option-content' });
    await userEvent.click(option);
    await userEvent.click(within(dialog).getByRole('button', { name: 'common.confirm' }));
    await waitFor(() => expect(fx.updateMembers).toHaveBeenCalledWith(31, ['alice', 'bob']));
    expect(fx.updateGroup).toHaveBeenCalledWith(31, { group_name: 'Group A', group_description: 'Fixture group' });
    expect(fx.updateMembers).toHaveBeenCalledOnce();
    await waitFor(() => expect(fx.refetchUsers).toHaveBeenCalled());
  });
  it('failed member update keeps edit dialog open instead of reporting success', async () => {
    fx.updateMembers.mockRejectedValueOnce(new Error('members rejected'));
    renderGroups();
    await userEvent.click(within(screen.getByText('Group A').closest('tr')!).getAllByRole('button')[1]);
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: 'common.confirm' }));
    await waitFor(() => expect(fx.updateMembers).toHaveBeenCalledOnce());
    expect(await screen.findByText('members rejected')).toBeTruthy();
    expect(screen.getByRole('dialog')).toBeTruthy();
    expect(fx.refetchUsers).not.toHaveBeenCalled();
  });
  it('expired invitation is displayed using its expired state', () => {
    render(<InvitationList tenantId="component-tenant" />);
    expect(screen.getByText('tenantResources.invitation.status.EXPIRE')).toBeTruthy();
    expect(screen.queryByText('tenantResources.invitation.status.IN_USE')).toBeNull();
  });
  it('form normalizes code, retains selected group and formats expiry for create', async () => {
    const dialog = await openInvite();
    const code = within(dialog).getByPlaceholderText('tenantResources.invitation.invitationCodePlaceholder');
    fireEvent.change(code, { target: { value: 'ab-12' } });
    expect(code).toHaveValue('AB12');
    const date = within(dialog).getByPlaceholderText('tenantResources.invitation.expiryDatePlaceholder');
    fireEvent.change(date, { target: { value: '2099-01-02' } });
    fireEvent.keyDown(date, { key: 'Enter', code: 'Enter' });
    await userEvent.click(within(dialog).getByRole('button', { name: 'common.confirm' }));
    await waitFor(() => expect(fx.createInvitation).toHaveBeenCalledOnce());
    expect(fx.createInvitation).toHaveBeenCalledWith(expect.objectContaining({
      tenant_id: 'component-tenant', invitation_code: 'AB12', code_type: 'USER_INVITE',
      group_ids: [31], expiry_date: '2099-01-02',
    }));
    expect(fx.refetchInvites).toHaveBeenCalled();
  });
  it('invalid capacity blocks create before the service boundary', async () => {
    const dialog = await openInvite();
    fireEvent.change(within(dialog).getByPlaceholderText('tenantResources.invitation.capacity'), { target: { value: '0' } });
    await userEvent.click(within(dialog).getByRole('button', { name: 'common.confirm' }));
    expect(await screen.findByText('tenantResources.invitation.capacityMin')).toBeTruthy();
    expect(fx.createInvitation).not.toHaveBeenCalled();
  });
});
