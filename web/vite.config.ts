import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  base: '/',
  plugins: [react(), tailwindcss()],
  build: {
    outDir: '../src/bactalk/static-next',
    emptyOutDir: true,
    sourcemap: false,
    // Keep the heavy visualization runtimes in their own chunks so the shell
    // paints before any canvas library downloads.
    rollupOptions: {
      output: {
        manualChunks(id) {
          // Shared state libraries stay out of the canvas chunks so the entry never preloads a canvas.
          if (id.includes('node_modules/zustand') || id.includes('node_modules/use-sync-external-store')) return 'state';
          if (id.includes('node_modules/@xyflow')) return 'xyflow';
          if (id.includes('node_modules/uplot')) return 'uplot';
          if (id.includes('node_modules/three') || id.includes('@react-three')) return 'three';
          if (id.includes('node_modules/motion') || id.includes('framer-motion')) return 'motion';
          // React itself is shared by every chunk; kept apart so a canvas chunk is never
          // what the entry preloads for the JSX runtime.
          if (/node_modules\/(react|react-dom|scheduler)\//.test(id)) return 'react';
          return undefined;
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8011',
    },
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      reporter: ['text-summary', 'json-summary'],
      reportsDirectory: '../artifacts/web-coverage',
      // The parts of the app that decide what a reviewer sees must be tested,
      // not just rendered: the trace engine, the stores, the semantic diff.
      include: ['src/trace/**', 'src/stores/**', 'src/features/wiresheet/diff/**'],
      exclude: ['src/**/*.test.{ts,tsx}'],
      thresholds: { lines: 80, functions: 80, branches: 70, statements: 80 },
    },
    setupFiles: ['./src/test/setup.ts'],
  },
});
