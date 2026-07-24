import { create } from "zustand";

interface setGlobalConfig {
    config: Record<string, string>;
    setConfig: (value: Record<string, string>) => void;
}

interface setGlobalConfigAll {
    configAll: any;
    setAllConfig: (value: any) => void;
}

export const useGlobalConfigStore = create<setGlobalConfig>((set) => ({
    config: {},
    setConfig: (value) => set({ config: value })
}));

export const useGlobalConfigStoreAllLanguage = create<setGlobalConfigAll>((set) => ({
    configAll: {},
    setAllConfig: (value) => set({ configAll: value })
}));