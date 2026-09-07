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
      if (event.key === 'Escape') closePreview()
    })
  }
} satisfies Theme
