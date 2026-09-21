import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  base: '/next/',
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
          if (id.includes('node_modules/@xyflow')) return 'xyflow';
          if (id.includes('node_modules/uplot')) return 'uplot';
          if (id.includes('node_modules/echarts') || id.includes('node_modules/zrender')) return 'echarts';
          if (id.includes('node_modules/three') || id.includes('@react-three')) return 'three';
          if (id.includes('node_modules/motion') || id.includes('framer-motion')) return 'motion';
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
    setupFiles: ['./src/test/setup.ts'],
  },
});
