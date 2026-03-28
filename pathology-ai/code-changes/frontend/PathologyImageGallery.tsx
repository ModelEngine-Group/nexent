"use client";

import React, { useState, useCallback } from "react";
import { ChevronLeft, ChevronRight, X, ZoomIn, ZoomOut, Download, ExternalLink } from "lucide-react";

// 病理图片类型
export interface PathologyImage {
  id: string;
  url: string;
  title: string;
  category: string;
  description?: string;
  magnification?: string;
  staining?: string;
}

// 组件属性
interface PathologyImageGalleryProps {
  images: PathologyImage[];
  className?: string;
  columns?: 2 | 3 | 4;
  showDetails?: boolean;
  onImageClick?: (image: PathologyImage) => void;
}

// 分类颜色映射
const categoryColors: Record<string, string> = {
  "Immunopathology": "bg-purple-100 text-purple-800",
  "Pulmonary": "bg-blue-100 text-blue-800",
  "Cardiovascular": "bg-red-100 text-red-800",
  "Neoplasia": "bg-orange-100 text-orange-800",
  "Neuropathology": "bg-indigo-100 text-indigo-800",
  "Gastrointestinal": "bg-green-100 text-green-800",
  "Hematopathology": "bg-pink-100 text-pink-800",
  "Inflammation": "bg-yellow-100 text-yellow-800",
  "Histology": "bg-teal-100 text-teal-800",
  "ElectronMicroscopy": "bg-gray-100 text-gray-800",
  "default": "bg-slate-100 text-slate-800",
};

// 获取分类颜色
const getCategoryColor = (category: string): string => {
  return categoryColors[category] || categoryColors["default"];
};

// 分类中文名映射
const categoryNames: Record<string, string> = {
  "Immunopathology": "免疫病理",
  "Pulmonary": "肺部病理",
  "Cardiovascular": "心血管病理",
  "Neoplasia": "肿瘤病理",
  "Neuropathology": "神经病理",
  "Gastrointestinal": "消化系统",
  "Hematopathology": "血液病理",
  "Inflammation": "炎症病理",
  "Histology": "组织学",
  "ElectronMicroscopy": "电子显微镜",
};

// 获取分类中文名
const getCategoryName = (category: string): string => {
  return categoryNames[category] || category;
};

export const PathologyImageGallery: React.FC<PathologyImageGalleryProps> = ({
  images,
  className = "",
  columns = 3,
  showDetails = true,
  onImageClick,
}) => {
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [zoom, setZoom] = useState(1);

  // 打开大图预览
  const openPreview = useCallback((index: number) => {
    setSelectedIndex(index);
    setZoom(1);
  }, []);

  // 关闭预览
  const closePreview = useCallback(() => {
    setSelectedIndex(null);
    setZoom(1);
  }, []);

  // 上一张
  const prevImage = useCallback(() => {
    if (selectedIndex !== null && selectedIndex > 0) {
      setSelectedIndex(selectedIndex - 1);
      setZoom(1);
    }
  }, [selectedIndex]);

  // 下一张
  const nextImage = useCallback(() => {
    if (selectedIndex !== null && selectedIndex < images.length - 1) {
      setSelectedIndex(selectedIndex + 1);
      setZoom(1);
    }
  }, [selectedIndex, images.length]);

  // 缩放
  const handleZoom = useCallback((delta: number) => {
    setZoom((prev) => Math.max(0.5, Math.min(3, prev + delta)));
  }, []);

  // 键盘事件
  React.useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (selectedIndex === null) return;
      switch (e.key) {
        case "Escape":
          closePreview();
          break;
        case "ArrowLeft":
          prevImage();
          break;
        case "ArrowRight":
          nextImage();
          break;
        case "+":
        case "=":
          handleZoom(0.25);
          break;
        case "-":
          handleZoom(-0.25);
          break;
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [selectedIndex, closePreview, prevImage, nextImage, handleZoom]);

  // 网格列数样式
  const gridCols = {
    2: "grid-cols-2",
    3: "grid-cols-2 md:grid-cols-3",
    4: "grid-cols-2 md:grid-cols-3 lg:grid-cols-4",
  };

  if (images.length === 0) {
    return (
      <div className={`flex items-center justify-center p-8 bg-gray-50 rounded-lg ${className}`}>
        <div className="text-center text-gray-500">
          <span className="text-4xl mb-2 block">🔬</span>
          <p>暂无病理图片</p>
        </div>
      </div>
    );
  }

  return (
    <div className={className}>
      {/* 图片网格 */}
      <div className={`grid ${gridCols[columns]} gap-4`}>
        {images.map((image, index) => (
          <div
            key={image.id}
            className="group relative bg-white rounded-lg shadow-md overflow-hidden cursor-pointer hover:shadow-lg transition-all duration-300 border border-gray-200"
            onClick={() => {
              openPreview(index);
              onImageClick?.(image);
            }}
          >
            {/* 图片 */}
            <div className="aspect-square overflow-hidden bg-gray-100">
              <img
                src={image.url}
                alt={image.title}
                className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                loading="lazy"
                onError={(e) => {
                  (e.target as HTMLImageElement).src = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='200'%3E%3Crect fill='%23f3f4f6' width='200' height='200'/%3E%3Ctext fill='%239ca3af' x='50%25' y='50%25' text-anchor='middle' dy='.3em'%3E🔬%3C/text%3E%3C/svg%3E";
                }}
              />
            </div>

            {/* 分类标签 */}
            <div className="absolute top-2 left-2">
              <span className={`px-2 py-1 text-xs font-medium rounded-full ${getCategoryColor(image.category)}`}>
                {getCategoryName(image.category)}
              </span>
            </div>

            {/* 放大图标 */}
            <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
              <div className="p-1.5 bg-black/50 rounded-full text-white">
                <ZoomIn className="w-4 h-4" />
              </div>
            </div>

            {/* 详情 */}
            {showDetails && (
              <div className="p-3">
                <h3 className="text-sm font-medium text-gray-900 truncate">{image.title}</h3>
                {image.description && (
                  <p className="text-xs text-gray-500 mt-1 line-clamp-2">{image.description}</p>
                )}
                <div className="flex gap-2 mt-2 flex-wrap">
                  {image.magnification && (
                    <span className="text-xs bg-gray-100 px-2 py-0.5 rounded text-gray-600">
                      {image.magnification}
                    </span>
                  )}
                  {image.staining && (
                    <span className="text-xs bg-gray-100 px-2 py-0.5 rounded text-gray-600">
                      {image.staining}
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>
        ))}
      </div>

      {/* 大图预览模态框 */}
      {selectedIndex !== null && (
        <div
          className="fixed inset-0 z-50 bg-black/90 flex items-center justify-center"
          onClick={closePreview}
        >
          {/* 工具栏 */}
          <div className="absolute top-4 right-4 flex gap-2 z-10">
            <button
              className="p-2 bg-white/10 hover:bg-white/20 rounded-full text-white transition-colors"
              onClick={(e) => {
                e.stopPropagation();
                handleZoom(-0.25);
              }}
            >
              <ZoomOut className="w-5 h-5" />
            </button>
            <button
              className="p-2 bg-white/10 hover:bg-white/20 rounded-full text-white transition-colors"
              onClick={(e) => {
                e.stopPropagation();
                handleZoom(0.25);
              }}
            >
              <ZoomIn className="w-5 h-5" />
            </button>
            <a
              href={images[selectedIndex].url}
              target="_blank"
              rel="noopener noreferrer"
              className="p-2 bg-white/10 hover:bg-white/20 rounded-full text-white transition-colors"
              onClick={(e) => e.stopPropagation()}
            >
              <ExternalLink className="w-5 h-5" />
            </a>
            <button
              className="p-2 bg-white/10 hover:bg-white/20 rounded-full text-white transition-colors"
              onClick={closePreview}
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* 图片计数 */}
          <div className="absolute top-4 left-4 text-white/80 text-sm">
            {selectedIndex + 1} / {images.length}
          </div>

          {/* 左箭头 */}
          {selectedIndex > 0 && (
            <button
              className="absolute left-4 p-3 bg-white/10 hover:bg-white/20 rounded-full text-white transition-colors"
              onClick={(e) => {
                e.stopPropagation();
                prevImage();
              }}
            >
              <ChevronLeft className="w-6 h-6" />
            </button>
          )}

          {/* 图片 */}
          <div
            className="max-w-[90vw] max-h-[85vh] overflow-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <img
              src={images[selectedIndex].url}
              alt={images[selectedIndex].title}
              className="max-w-none transition-transform duration-200"
              style={{ transform: `scale(${zoom})`, transformOrigin: "center" }}
            />
          </div>

          {/* 右箭头 */}
          {selectedIndex < images.length - 1 && (
            <button
              className="absolute right-4 p-3 bg-white/10 hover:bg-white/20 rounded-full text-white transition-colors"
              onClick={(e) => {
                e.stopPropagation();
                nextImage();
              }}
            >
              <ChevronRight className="w-6 h-6" />
            </button>
          )}

          {/* 底部信息 */}
          <div className="absolute bottom-4 left-0 right-0 text-center text-white">
            <h3 className="text-lg font-medium">{images[selectedIndex].title}</h3>
            <p className="text-sm text-white/70 mt-1">
              {getCategoryName(images[selectedIndex].category)}
              {images[selectedIndex].magnification && ` · ${images[selectedIndex].magnification}`}
              {images[selectedIndex].staining && ` · ${images[selectedIndex].staining}`}
            </p>
            {images[selectedIndex].description && (
              <p className="text-sm text-white/60 mt-2 max-w-2xl mx-auto">
                {images[selectedIndex].description}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default PathologyImageGallery;
