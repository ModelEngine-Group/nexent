import '@testing-library/jest-dom';
import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CiteMarker } from '@/app/[locale]/newchat/ui/cite-marker';

vi.mock('@/components/ui/tooltip', () => {
  const React = require('react');
  const TooltipContext = React.createContext({ open: false, setOpen: (_v: any) => {} });
  const TooltipProvider = ({ children }: any) => {
    const [open, setOpen] = React.useState(false);
    return React.createElement(TooltipContext.Provider, { value: { open, setOpen } }, children);
  };
  const Tooltip = ({ children }: any) => React.createElement(React.Fragment, null, children);
  const TooltipTrigger = ({ asChild, children }: any) => {
    const { setOpen } = React.useContext(TooltipContext);
    const openFn = () => setOpen(true);
    const close = () => setOpen(false);
    if (asChild && React.isValidElement(children)) {
      return React.cloneElement(children as any, {
        onPointerEnter: (e: any) => { openFn(); (children as any).props.onPointerEnter?.(e); },
        onMouseEnter: (e: any) => { openFn(); (children as any).props.onMouseEnter?.(e); },
        onFocus: (e: any) => { openFn(); (children as any).props.onFocus?.(e); },
        onBlur: (e: any) => { close(); (children as any).props.onBlur?.(e); },
      });
    }
    return React.createElement('button', null, children);
  };
  const TooltipContent = ({ children, ...props }: any) => {
    const { open } = React.useContext(TooltipContext);
    if (!open) return null;
    return React.createElement('div', { 'data-testid': 'tooltip-content', ...props }, children);
  };
  return { TooltipProvider, Tooltip, TooltipTrigger, TooltipContent };
});

const baseProps = {
  citekey: ' B1 ',
  displayIndex: 3,
  sourceIndex: 2,
  label: 'source',
  title: 'My Title',
  text: 'Retrieved chunk text',
  filename: 'report.pdf',
  url: 'https://example.com/a',
  sourceType: 'document' as const,
  sourceLabel: '来源: Nexent',
};

const whitelistHtml = '<p>Para <strong>bold</strong> and <em>italic</em></p><br/><table><thead><tr><th>Header</th></tr></thead><tbody><tr><td>Cell</td></tr></tbody></table>';
const blacklistHtml = '<p>Keep</p><script>alert(1)</script><img src=x onerror=alert(2)><a href=evil>link</a><div class=x>block</div>';

const openTooltip = async () => screen.findByTestId('tooltip-content');

describe('CiteMarker', () => {
  it('UT-FE-AUTO-0330CCC385F313B2 renders badge with display index, data attributes and aria-label', () => {
    render(<CiteMarker {...baseProps} />);
    const button = screen.getByRole('button');
    expect(button).toHaveAttribute('type', 'button');
    expect(button).toHaveAttribute('data-citation-marker');
    expect(button).toHaveAttribute('data-citekey', 'b1');
    expect(button).toHaveAttribute('data-citation-source-index', '2');
    expect(button).toHaveAttribute('data-citation-display-index', '3');
    expect(button).toHaveAttribute('aria-label', 'Open source: My Title');
    expect(button).toHaveTextContent('3');
  });

  it('shows title and a consistent CiteIndexBadge index in the hover card', async () => {
    const user = userEvent.setup();
    render(<CiteMarker {...baseProps} />);
    await user.hover(screen.getByRole('button'));
    const content = await openTooltip();
    expect(within(content).getByText('My Title')).toBeInTheDocument();
    expect(within(content).getByText('3')).toBeInTheDocument();
  });

  it('renders DatabaseIcon and filename/sourceLabel for document sources', async () => {
    const user = userEvent.setup();
    render(<CiteMarker {...baseProps} />);
    await user.hover(screen.getByRole('button'));
    const content = await openTooltip();
    expect(content.querySelector('.lucide-database')).toBeTruthy();
    expect(content.querySelector('.lucide-external-link')).toBeFalsy();
    expect(within(content).getByText('report.pdf')).toBeInTheDocument();
    expect(within(content).getByText('来源: Nexent')).toBeInTheDocument();
  });

  it('renders ExternalLinkIcon and filename fallback for url sources', async () => {
    const user = userEvent.setup();
    const urlProps = { ...baseProps, title: '', filename: '', url: 'https://example.com/doc', sourceType: 'url' as const, sourceLabel: '' };
    render(<CiteMarker {...urlProps} />);
    await user.hover(screen.getByRole('button'));
    const content = await openTooltip();
    expect(content.querySelector('.lucide-external-link')).toBeTruthy();
    expect(content.querySelector('.lucide-database')).toBeFalsy();
    expect(within(content).getByText('https://example.com/doc')).toBeInTheDocument();
    expect(content.querySelector('.lucide-server')).toBeFalsy();
  });

  it('falls back to title when filename and url are empty', async () => {
    const user = userEvent.setup();
    render(<CiteMarker {...baseProps} filename={''} url={''} />);
    await user.hover(screen.getByRole('button'));
    const content = await openTooltip();
    expect(within(content).getAllByText('My Title')).toHaveLength(2);
  });

  it('renders whitelisted HTML tags semantically', async () => {
    const user = userEvent.setup();
    render(<CiteMarker {...baseProps} text={whitelistHtml} />);
    await user.hover(screen.getByRole('button'));
    const content = await openTooltip();
    expect(content.querySelector('p')).toBeTruthy();
    expect(content.querySelector('strong')).toBeTruthy();
    expect(content.querySelector('em')).toBeTruthy();
    expect(content.querySelector('br')).toBeTruthy();
    expect(content.querySelector('table')).toBeTruthy();
    expect(content.querySelector('th')).toBeTruthy();
    expect(content.querySelector('td')).toBeTruthy();
    expect(within(content).getByText('bold')).toBeInTheDocument();
    expect(within(content).getByText('italic')).toBeInTheDocument();
    expect(within(content).getByText('Header')).toBeInTheDocument();
    expect(within(content).getByText('Cell')).toBeInTheDocument();
  });

  it('strips non-whitelisted tags without executing them', async () => {
    const user = userEvent.setup();
    render(<CiteMarker {...baseProps} text={blacklistHtml} />);
    await user.hover(screen.getByRole('button'));
    const content = await openTooltip();
    expect(content.querySelector('script')).toBeNull();
    expect(content.querySelector('img')).toBeNull();
    expect(content.querySelector('a')).toBeNull();
    expect(content.querySelector('[onerror]')).toBeNull();
    expect(within(content).getByText('Keep')).toBeInTheDocument();
  });

  it('omits the preview region when text is empty or whitespace', async () => {
    const user = userEvent.setup();
    render(<CiteMarker {...baseProps} text={'   '} />);
    await user.hover(screen.getByRole('button'));
    const content = await openTooltip();
    const previews = Array.from(content.querySelectorAll('div')).filter((el) => (el as HTMLElement).className.includes('max-h-64'));
    expect(previews).toHaveLength(0);
  });

  it('disables the badge and shows loading text when loading', async () => {
    render(<CiteMarker {...baseProps} loading />);
    const button = screen.getByRole('button');
    expect(button).toBeDisabled();
    fireEvent.mouseOver(button);
    const content = await openTooltip();
    expect(within(content).getByText('Source details are loading')).toBeInTheDocument();
  });

  it('is interactive without loading and invokes onClick with the marker', async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();
    render(<CiteMarker {...baseProps} onClick={onClick} />);
    const button = screen.getByRole('button');
    expect(button).not.toBeDisabled();
    await user.click(button);
    expect(onClick).toHaveBeenCalledTimes(1);
    expect(onClick).toHaveBeenCalledWith(button);
  });

  it('activates via Enter and Space like a click', async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();
    render(<CiteMarker {...baseProps} onClick={onClick} />);
    const button = screen.getByRole('button');
    await user.tab();
    expect(button).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(onClick).toHaveBeenCalledTimes(1);
    expect(onClick).toHaveBeenCalledWith(button);
    await user.keyboard(' ');
    expect(onClick).toHaveBeenCalledTimes(2);
  });

  it('is memoized and cleans up on unmount', () => {
    const onClick = vi.fn();
    const { container, unmount } = render(<CiteMarker {...baseProps} onClick={onClick} />);
    expect((CiteMarker as any).$$typeof).toBe(Symbol.for('react.memo'));
    unmount();
    expect(container).toBeEmptyDOMElement();
  });
});
