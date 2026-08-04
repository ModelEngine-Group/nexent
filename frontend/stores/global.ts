import { create } from "zustand";

interface SetGlobalConfig {
    config: Record<string, string>;
    setConfig: (value: Record<string, string>) => void;
}

interface SetGlobalConfigAll {
    configAll: any;
    setAllConfig: (value: any) => void;
}

export const useGlobalConfigStore = create<SetGlobalConfig>((set) => ({
    config: {},
    setConfig: (value) => set({ config: value })
}));

export const useGlobalConfigStoreAllLanguage = create<SetGlobalConfigAll>((set) => ({
    configAll: {},
    setAllConfig: (value) => set({ configAll: value })
}));