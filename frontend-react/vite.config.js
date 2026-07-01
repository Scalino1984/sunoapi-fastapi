import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ command }) => ({
  base: command === 'build' ? '/react/' : '/',
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/auth': 'http://127.0.0.1:8000',
      '/media': 'http://127.0.0.1:8000'
    }
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    // Die App ist bewusst ein umfangreiches internes Studio.
    // Der aktuelle Haupt-Chunk liegt nur knapp über Vites Standardwarnung von 500 kB.
    // Diese Grenze entfernt die kosmetische Build-Warnung, ohne Bundle-Logik zu verändern.
    chunkSizeWarningLimit: 2048
  }
}));
