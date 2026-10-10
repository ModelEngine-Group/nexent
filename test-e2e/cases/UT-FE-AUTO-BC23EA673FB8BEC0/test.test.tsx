import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import type { TFunction } from 'i18next';

import { getTagSearchPredicates } from '@/lib/systemTagLabels';
import TagFilterControls from '@/components/tag/TagFilterControls';
import RepositoryTagFilter from '@/components/tag/RepositoryTagFilter';
import type { TagDefinition, TagValue } from '@/types/tagManagement';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts && 'defaultValue' in opts ? String(opts.defaultValue) : key,
  }),
}));

if (typeof window !== 'undefined') {
  if (!window.matchMedia) {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: (query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      }),
    });
  }
  if (!('ResizeObserver' in window)) {
    (window as unknown as { ResizeObserver: unknown }).ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
  }
}

const t = ((key: string) => key) as TFunction;

function tagValue(overrides: Partial<TagValue> = {}): TagValue {
  return {
    value_id: 1,
    display_value: 'Alpha',
    normalized_value: 'alpha',
    sort_order: 0,
    status: 'active',
    ...overrides,
  };
}

function tagDefinition(overrides: Partial<TagDefinition> = {}): TagDefinition {
  return {
    definition_id: 1,
    bucket_id: 100,
    definition_key: 'category',
    definition_name: 'Category',
    selection_mode: 'single_select',
    sort_order: 0,
    status: 'active',
    active_value_count: 0,
    value_capacity: 100,
    values: [],
    ...overrides,
  };
}

describe('getTagSearchPredicates', () => {
  it('UT-FE-AUTO-BC23EA673FB8BEC0 returns no predicates for an empty or whitespace search', () => {
    const defs = [tagDefinition({ values: [tagValue({ value_id: 1 })] })];
    expect(getTagSearchPredicates(defs, '', t)).toEqual([]);
    expect(getTagSearchPredicates(defs, '   ', t)).toEqual([]);
  });

  it('returns no predicates when definitions are missing', () => {
    expect(getTagSearchPredicates(null, 'alpha', t)).toEqual([]);
    expect(getTagSearchPredicates(undefined, 'alpha', t)).toEqual([]);
  });

  it('matches every active value when the definition name matches', () => {
    const defs = [
      tagDefinition({
        definition_id: 10,
        definition_name: 'Deployment',
        values: [
          tagValue({ value_id: 1, display_value: 'Cloud', normalized_value: 'cloud' }),
          tagValue({ value_id: 2, display_value: 'Local', normalized_value: 'local' }),
          tagValue({ value_id: 3, display_value: 'Disabled', normalized_value: 'disabled', status: 'disabled' }),
        ],
      }),
    ];
    expect(getTagSearchPredicates(defs, 'deploy', t)).toEqual([
      { definition_id: 10, value_ids: [1, 2] },
    ]);
  });

  it('matches the definition key', () => {
    const defs = [
      tagDefinition({
        definition_id: 11,
        definition_key: 'runtime-kind',
        definition_name: 'Runtime Kind',
        values: [tagValue({ value_id: 5, display_value: 'Node', normalized_value: 'node' })],
      }),
    ];
    expect(getTagSearchPredicates(defs, 'runtime-k', t)).toEqual([
      { definition_id: 11, value_ids: [5] },
    ]);
  });

  it('narrows to a single value when only that value matches', () => {
    const defs = [
      tagDefinition({
        definition_id: 12,
        values: [
          tagValue({ value_id: 1, display_value: 'Alpha', normalized_value: 'alpha' }),
          tagValue({ value_id: 2, display_value: 'Beta', normalized_value: 'beta' }),
        ],
      }),
    ];
    expect(getTagSearchPredicates(defs, 'beta', t)).toEqual([
      { definition_id: 12, value_ids: [2] },
    ]);
  });

  it('matches the normalized value text', () => {
    const defs = [
      tagDefinition({
        definition_id: 13,
        values: [tagValue({ value_id: 7, display_value: 'Alpha', normalized_value: 'alpha_ml' })],
      }),
    ];
    expect(getTagSearchPredicates(defs, 'alpha_ml', t)).toEqual([
      { definition_id: 13, value_ids: [7] },
    ]);
  });

  it('returns an empty array when nothing matches', () => {
    const defs = [
      tagDefinition({
        definition_id: 14,
        values: [tagValue({ value_id: 1, display_value: 'Alpha', normalized_value: 'alpha' })],
      }),
    ];
    expect(getTagSearchPredicates(defs, 'zzz-no-match', t)).toEqual([]);
  });

  it('emits one predicate per matching definition', () => {
    const defs = [
      tagDefinition({
        definition_id: 1,
        values: [tagValue({ value_id: 11, display_value: 'Alpha', normalized_value: 'alpha' })],
      }),
      tagDefinition({
        definition_id: 2,
        definition_name: 'Scope',
        values: [
          tagValue({ value_id: 21, display_value: 'Public', normalized_value: 'public' }),
          tagValue({ value_id: 22, display_value: 'Private', normalized_value: 'private' }),
        ],
      }),
    ];
    expect(getTagSearchPredicates(defs, 'alpha', t)).toEqual([
      { definition_id: 1, value_ids: [11] },
    ]);
    expect(getTagSearchPredicates(defs, 'scope', t)).toEqual([
      { definition_id: 2, value_ids: [21, 22] },
    ]);
  });

  it('omits definitions whose matching value set is empty', () => {
    const defs = [
      tagDefinition({
        definition_id: 1,
        values: [tagValue({ value_id: 1, display_value: 'Alpha', normalized_value: 'alpha' })],
      }),
      tagDefinition({
        definition_id: 2,
        values: [tagValue({ value_id: 2, display_value: 'Beta', normalized_value: 'beta' })],
      }),
    ];
    expect(getTagSearchPredicates(defs, 'alpha', t)).toEqual([
      { definition_id: 1, value_ids: [1] },
    ]);
  });
});

describe('TagFilterControls', () => {
  it('renders an empty state when there are no active definitions', () => {
    render(<TagFilterControls definitions={[]} value={[]} onChange={() => {}} />);
    expect(screen.getByText('tagManagement.empty.noActiveDefinitions')).toBeTruthy();
  });

  it('toggles a no_value predicate through the checkbox', () => {
    const onChange = vi.fn();
    const defs = [
      tagDefinition({
        definition_id: 5,
        selection_mode: 'no_value',
        values: [tagValue({ value_id: 9, display_value: 'HasValue', normalized_value: 'has_value' })],
      }),
    ];
    render(<TagFilterControls definitions={defs} value={[]} onChange={onChange} />);
    fireEvent.click(screen.getByRole('checkbox'));
    expect(onChange).toHaveBeenCalledWith([{ definition_id: 5, value_ids: [9] }]);
  });

  it('clears a no_value predicate when unchecked', () => {
    const onChange = vi.fn();
    const defs = [
      tagDefinition({
        definition_id: 5,
        selection_mode: 'no_value',
        values: [tagValue({ value_id: 9, display_value: 'HasValue', normalized_value: 'has_value' })],
      }),
    ];
    render(
      <TagFilterControls
        definitions={defs}
        value={[{ definition_id: 5, value_ids: [9] }]}
        onChange={onChange}
      />
    );
    fireEvent.click(screen.getByRole('checkbox'));
    expect(onChange).toHaveBeenCalledWith([]);
  });

  it('emits a predicate when a single-select value is chosen', async () => {
    const onChange = vi.fn();
    const defs = [
      tagDefinition({
        definition_id: 6,
        values: [
          tagValue({ value_id: 1, display_value: 'Alpha', normalized_value: 'alpha' }),
          tagValue({ value_id: 2, display_value: 'Beta', normalized_value: 'beta' }),
        ],
      }),
    ];
    const { container } = render(
      <TagFilterControls definitions={defs} value={[]} onChange={onChange} />
    );
    const selectors = screen.getAllByRole('combobox');
    fireEvent.mouseDown(selectors[selectors.length - 1]);
    fireEvent.click(await screen.findByText('Beta'));
    expect(onChange).toHaveBeenCalledWith([{ definition_id: 6, value_ids: [2] }]);
  });

  it('emits multiple value ids in multi-select mode', async () => {
    const onChange = vi.fn();
    const defs = [
      tagDefinition({
        definition_id: 7,
        selection_mode: 'multi_select',
        values: [
          tagValue({ value_id: 1, display_value: 'Alpha', normalized_value: 'alpha' }),
          tagValue({ value_id: 2, display_value: 'Beta', normalized_value: 'beta' }),
        ],
      }),
    ];
    const { rerender } = render(
      <TagFilterControls definitions={defs} value={[]} onChange={onChange} />
    );
    const selectors = screen.getAllByRole('combobox');
    fireEvent.mouseDown(selectors[selectors.length - 1]);
    fireEvent.click(await screen.findByText('Alpha'));
    rerender(
      <TagFilterControls
        definitions={defs}
        value={[{ definition_id: 7, value_ids: [1] }]}
        onChange={onChange}
      />
    );
    fireEvent.mouseDown(screen.getAllByRole('combobox').at(-1)!);
    fireEvent.click(await screen.findByText('Beta'));
    expect(onChange).toHaveBeenLastCalledWith([
      { definition_id: 7, value_ids: [1, 2] },
    ]);
  });
});

describe('RepositoryTagFilter', () => {
  const tags = [
    { tag: 'ml', count: 3 },
    { tag: 'agent', count: 1 },
  ];

  it('renders the filter trigger button', () => {
    render(<RepositoryTagFilter value={undefined} tags={tags} onChange={() => {}} />);
    expect(screen.getByRole('button', { name: 'repository.tagFilter.button' })).toBeTruthy();
  });

  it('emits the selected tag when an option is chosen', async () => {
    const onChange = vi.fn();
    render(<RepositoryTagFilter value={undefined} tags={tags} onChange={onChange} />);
    fireEvent.click(screen.getByRole('button', { name: 'repository.tagFilter.button' }));
    fireEvent.mouseDown(screen.getByRole('combobox'));
    fireEvent.click(await screen.findByText('ml (3)'));
    expect(onChange).toHaveBeenCalledWith('ml');
  });

  it('emits undefined from the clear button to reset to FILTER_ALL', () => {
    const onChange = vi.fn();
    render(<RepositoryTagFilter value="ml" tags={tags} onChange={onChange} />);
    fireEvent.click(screen.getByRole('button', { name: 'repository.tagFilter.button' }));
    fireEvent.click(screen.getByRole('button', { name: 'repository.tagFilter.clear' }));
    expect(onChange).toHaveBeenCalledWith(undefined);
  });
});
