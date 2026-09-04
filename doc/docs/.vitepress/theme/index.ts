// https://vitepress.dev/guide/custom-theme
import { h } from 'vue'
import type { Theme } from 'vitepress'
import DefaultTheme from 'vitepress/theme'
import './style.css'

let preview: HTMLDivElement | undefined

const closePreview = () => {
  preview?.classList.remove('is-visible')
  preview?.replaceChildren()
}

const showPreview = (image: HTMLImageElement) => {
  if (!preview) return

  const previewImage = new Image()
  previewImage.src = image.currentSrc || image.src
  previewImage.alt = image.alt
  preview.replaceChildren(previewImage)
  preview.classList.add('is-visible')
}

/* -------------------------------------------------------------------------- */
/* Mermaid diagrams: runtime render + pan / zoom / fullscreen controller      */
/* -------------------------------------------------------------------------- */

type MermaidModule = typeof import('mermaid')['default']

const MIN_SCALE = 0.25
const MAX_SCALE = 4
const BUTTON_FACTOR = 1.2
const WHEEL_FACTOR = 1.1
const DRAG_THRESHOLD = 3

let mermaidModule: MermaidModule | undefined
let mermaidTheme = ''
let renderId = 0

const resolveTheme = () =>
  document.documentElement.classList.contains('dark') ? 'dark' : 'default'

async function loadMermaid(): Promise<MermaidModule> {
  if (!mermaidModule) mermaidModule = (await import('mermaid')).default
  const theme = resolveTheme()
  if (theme !== mermaidTheme) {
    mermaidTheme = theme
    mermaidModule.initialize({ startOnLoad: false, theme })
  }
  return mermaidModule
}

async function renderMermaid(source: string): Promise<string | undefined> {
  try {
    const mermaid = await loadMermaid()
    const { svg } = await mermaid.render(`mermaid-svg-${++renderId}`, source)
    return svg
  } catch (error) {
    console.warn('[mermaid] failed to render diagram:', error)
    return undefined
  }
}

const svgIcon = (paths: string) =>
  `<svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`

const ICONS = {
  plus: svgIcon('<path d="M8 3v10M3 8h10"/>'),
  minus: svgIcon('<path d="M3 8h10"/>'),
  reset: svgIcon('<path d="M5.5 2.5h-3v3M10.5 2.5h3v3M13.5 10.5v3h-3M5.5 13.5h-3v-3"/>'),
  fullscreen: svgIcon('<path d="M9.5 2.5h4v4M13 3l-4 4M6.5 13.5h-4v-4M3 13l4-4"/>'),
  close: svgIcon('<path d="M4 4l8 8M12 4l-8 8"/>')
}

function buildFigure(source: string, svg: string): HTMLElement {
  const figure = document.createElement('figure')
  figure.className = 'mermaid-figure'
  figure.dataset.mermaidSource = source

  const viewport = document.createElement('div')
  viewport.className = 'mermaid-viewport'

  const stage = document.createElement('div')
  stage.className = 'mermaid-stage'
  stage.innerHTML = svg

  const controls = document.createElement('div')
  controls.className = 'mermaid-controls'

  const zoomIn = button(ICONS.plus, 'Zoom in')
  const zoomOut = button(ICONS.minus, 'Zoom out')
  const reset = button(ICONS.reset, 'Reset view')
  const fullscreen = button(ICONS.fullscreen, 'Fullscreen')
  const label = document.createElement('span')
  label.className = 'mermaid-zoom-label'
  label.textContent = '100%'

  controls.append(zoomIn, label, zoomOut, reset, fullscreen)

  const close = button(ICONS.close, 'Exit fullscreen')
  close.className = 'mermaid-close'
  close.title = 'Exit fullscreen (Esc)'

  viewport.append(stage)
  figure.append(viewport, controls, close)

  createController(figure, { zoomIn, zoomOut, reset, fullscreen, close, label })

  return figure
}

function button(icon: string, title: string): HTMLButtonElement {
  const el = document.createElement('button')
  el.className = 'mermaid-btn'
  el.type = 'button'
  el.title = title
  el.setAttribute('aria-label', title)
  el.innerHTML = icon
  return el
}

interface ControllerRefs {
  zoomIn: HTMLButtonElement
  zoomOut: HTMLButtonElement
  reset: HTMLButtonElement
  fullscreen: HTMLButtonElement
  close: HTMLButtonElement
  label: HTMLSpanElement
}

interface DiagramMetrics {
  naturalW: number
  naturalH: number
  baseScale: number // fit-to-width scale shown as 100%
  padLeft: number
  padTop: number
  padY: number
}

// Capture the diagram's intrinsic size and the container's fit-to-width scale.
// Zooming resizes the SVG directly (vector re-render, sharp at any level),
// while the viewport keeps a FIXED height (the 100% fit) so zooming never
// changes the card size or shifts the page layout.
function readMetrics(viewport: HTMLElement, stage: HTMLElement): DiagramMetrics | undefined {
  const svg = stage.querySelector<SVGSVGElement>('svg')
  if (!svg) return undefined

  let w = 0
  let h = 0
  const viewBox = svg.getAttribute('viewBox')
  if (viewBox) {
    const parts = viewBox.trim().split(/[\s,]+/).map(Number)
    if (parts.length === 4 && parts[2] > 0 && parts[3] > 0) {
      w = parts[2]
      h = parts[3]
    }
  }
  if (!w || !h) {
    const rect = svg.getBoundingClientRect()
    w = rect.width
    h = rect.height
  }
  if (!w || !h) return undefined

  if (!viewBox) svg.setAttribute('viewBox', `0 0 ${w} ${h}`)
  svg.removeAttribute('width')
  svg.removeAttribute('height')
  svg.style.maxWidth = 'none'

  const style = getComputedStyle(viewport)
  const padLeft = parseFloat(style.paddingLeft) || 0
  const padRight = parseFloat(style.paddingRight) || 0
  const padTop = parseFloat(style.paddingTop) || 0
  const padBottom = parseFloat(style.paddingBottom) || 0
  const avail = viewport.clientWidth - padLeft - padRight
  const baseScale = avail > 0 ? Math.min(1, avail / w) : 1
  return { naturalW: w, naturalH: h, baseScale, padLeft, padTop, padY: padTop + padBottom }
}

function createController(figure: HTMLElement, refs: ControllerRefs): void {
  const viewport = figure.querySelector<HTMLElement>('.mermaid-viewport')!
  const stage = figure.querySelector<HTMLElement>('.mermaid-stage')!

  let metrics = readMetrics(viewport, stage)
  let scale = 1 // user zoom, 1 = fit to width
  let x = 0
  let y = 0
  let dragged = false

  const clamp = (value: number) => Math.min(MAX_SCALE, Math.max(MIN_SCALE, value))

  const apply = () => {
    const svg = stage.querySelector<SVGSVGElement>('svg')
    if (!metrics || !svg) return

    const eff = metrics.baseScale * scale
    svg.style.width = `${metrics.naturalW * eff}px`
    svg.style.height = `${metrics.naturalH * eff}px`
    stage.style.transform = `translate(${x}px, ${y}px)`

    // Fixed card height (the 100% fit); fullscreen layout is handled by CSS
    if (!figure.classList.contains('is-fullscreen')) {
      viewport.style.height = `${Math.ceil(metrics.naturalH * metrics.baseScale + metrics.padY)}px`
    } else {
      viewport.style.height = ''
    }

    refs.label.textContent = `${Math.round(scale * 100)}%`
    refs.zoomIn.disabled = scale >= MAX_SCALE
    refs.zoomOut.disabled = scale <= MIN_SCALE
  }

  const refresh = () => {
    metrics = readMetrics(viewport, stage)
    apply()
  }

  // Zoom keeping the given anchor (stage-local coords) fixed on screen
  const zoomAt = (anchorX: number, anchorY: number, nextScale: number) => {
    const clamped = clamp(nextScale)
    if (clamped === scale) return
    const ratio = clamped / scale
    x = anchorX - (anchorX - x) * ratio
    y = anchorY - (anchorY - y) * ratio
    scale = clamped
    apply()
  }

  const zoomCentered = (factor: number) => {
    zoomAt(viewport.clientWidth / 2, viewport.clientHeight / 2, scale * factor)
  }

  const resetView = () => {
    scale = 1
    x = 0
    y = 0
    apply()
  }

  const exitFullscreen = () => {
    figure.classList.remove('is-fullscreen')
    document.body.classList.remove('mermaid-fullscreen-active')
    x = 0
    y = 0
    refresh()
  }

  const enterFullscreen = () => {
    figure.classList.add('is-fullscreen')
    document.body.classList.add('mermaid-fullscreen-active')
    x = 0
    y = 0
    refresh()
  }

  // Ctrl + wheel zoom (anchored at the cursor); plain wheel keeps scrolling the page
  viewport.addEventListener(
    'wheel',
    (event) => {
      if (!(event instanceof WheelEvent) || !event.ctrlKey) return
      event.preventDefault()
      if (!metrics) return
      const rect = viewport.getBoundingClientRect()
      const factor = event.deltaY < 0 ? WHEEL_FACTOR : 1 / WHEEL_FACTOR
      // Convert cursor position to stage-local coordinates (subtract padding)
      zoomAt(
        event.clientX - rect.left - metrics.padLeft,
        event.clientY - rect.top - metrics.padTop,
        scale * factor
      )
    },
    { passive: false }
  )

  // Pointer drag to pan
  let drag: { pointerId: number; startX: number; startY: number; originX: number; originY: number } | undefined

  viewport.addEventListener('pointerdown', (event) => {
    if (!(event instanceof PointerEvent) || event.button !== 0) return
    drag = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      originX: x,
      originY: y
    }
    dragged = false
    viewport.setPointerCapture(event.pointerId)
  })

  viewport.addEventListener('pointermove', (event) => {
    if (!drag || event.pointerId !== drag.pointerId) return
    const dx = event.clientX - drag.startX
    const dy = event.clientY - drag.startY
    if (!dragged && Math.abs(dx) + Math.abs(dy) > DRAG_THRESHOLD) dragged = true
    if (!dragged) return
    x = drag.originX + dx
    y = drag.originY + dy
    apply()
  })

  const endDrag = (event: PointerEvent) => {
    if (!drag || event.pointerId !== drag.pointerId) return
    drag = undefined
    viewport.releasePointerCapture(event.pointerId)
  }
  viewport.addEventListener('pointerup', endDrag)
  viewport.addEventListener('pointercancel', endDrag)

  // Click on the backdrop (not after a drag) exits fullscreen
  figure.addEventListener('click', (event) => {
    if (!figure.classList.contains('is-fullscreen')) return
    if (dragged) return
    if (event.target === viewport || event.target === stage || event.target === figure) {
      exitFullscreen()
    }
  })

  refs.zoomIn.addEventListener('click', () => zoomCentered(BUTTON_FACTOR))
  refs.zoomOut.addEventListener('click', () => zoomCentered(1 / BUTTON_FACTOR))
  refs.reset.addEventListener('click', resetView)

  // Re-fit when the available width changes (window resize, sidebar toggle,
  // fullscreen enter/exit). Only width matters: the height is ours.
  let lastWidth = viewport.clientWidth
  const resizeObserver = new ResizeObserver(() => {
    const width = viewport.clientWidth
    if (width === lastWidth) return
    lastWidth = width
    refresh()
  })
  resizeObserver.observe(viewport)
  refs.fullscreen.addEventListener('click', () =>
    figure.classList.contains('is-fullscreen') ? exitFullscreen() : enterFullscreen()
  )
  refs.close.addEventListener('click', exitFullscreen)

  figure.dataset.mermaidController = 'ready'
  controllerByFigure.set(figure, { exitFullscreen, resetView, refresh })
}

interface FigureController {
  exitFullscreen: () => void
  resetView: () => void
  refresh: () => void
}

const controllerByFigure = new WeakMap<HTMLElement, FigureController>()

async function enhanceBlock(block: HTMLElement): Promise<boolean> {
  const source = block.querySelector('code')?.textContent?.trim()
  if (!source) return false

  const svg = await renderMermaid(source)
  if (!svg) return false

  const figure = buildFigure(source, svg)
  block.replaceWith(figure)
  // Capture the layout size now that the figure is in the DOM
  controllerByFigure.get(figure)?.refresh()
  return true
}

// Re-render existing figures when the color scheme switches
async function rerenderFigures(): Promise<void> {
  const figures = document.querySelectorAll<HTMLElement>('.mermaid-figure')
  if (!figures.length) return
  await loadMermaid() // re-initialize with the new theme
  for (const figure of figures) {
    const source = figure.dataset.mermaidSource
    if (!source) continue
    const svg = await renderMermaid(source)
    if (!svg) continue
    const stage = figure.querySelector<HTMLElement>('.mermaid-stage')
    if (stage) stage.innerHTML = svg
    // New SVG: re-capture its base size, keep the current zoom level
    controllerByFigure.get(figure)?.refresh()
  }
}

function setupMermaid(): void {
  let enhanceTimer: number | undefined
  let rerenderTimer: number | undefined
  let lastDark = document.documentElement.classList.contains('dark')

  const scheduleEnhance = () => {
    clearTimeout(enhanceTimer)
    enhanceTimer = window.setTimeout(() => {
      const blocks = document.querySelectorAll<HTMLElement>('div.language-mermaid:not([data-mermaid])')
      for (const block of blocks) {
        block.dataset.mermaid = 'pending'
        enhanceBlock(block).then((ok) => {
          if (!ok) block.dataset.mermaid = 'failed'
        })
      }
    }, 100)
  }

  // Handle initial load, route changes and hydration re-renders
  const observer = new MutationObserver(scheduleEnhance)
  observer.observe(document.body, { childList: true, subtree: true })
  scheduleEnhance()

  // Watch for light/dark theme switches
  new MutationObserver(() => {
    const dark = document.documentElement.classList.contains('dark')
    if (dark === lastDark) return
    lastDark = dark
    clearTimeout(rerenderTimer)
    rerenderTimer = window.setTimeout(rerenderFigures, 200)
  }).observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
}

export default {
  extends: DefaultTheme,
  Layout: () => {
    return h(DefaultTheme.Layout, null, {
      // https://vitepress.dev/guide/extending-default-theme#layout-slots
    })
  },
  enhanceApp() {
    if (typeof document === 'undefined' || preview) return

    preview = document.createElement('div')
    preview.className = 'image-preview'
    preview.setAttribute('role', 'dialog')
    preview.setAttribute('aria-modal', 'true')
    preview.setAttribute('aria-label', 'Image preview')
    preview.addEventListener('click', closePreview)
    document.body.append(preview)

    document.addEventListener('click', (event) => {
      const target = event.target
      if (!(target instanceof HTMLImageElement)) return
      if (!target.closest('.vp-doc') || target.closest('a')) return

      event.preventDefault()
      showPreview(target)
    })

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        closePreview()
        const fullscreen = document.querySelector<HTMLElement>('.mermaid-figure.is-fullscreen')
        if (fullscreen) controllerByFigure.get(fullscreen)?.exitFullscreen()
      }
    })

    setupMermaid()
  }
} satisfies Theme
