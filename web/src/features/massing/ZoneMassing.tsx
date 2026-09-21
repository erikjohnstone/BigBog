import { useEffect, useMemo, useRef, useState } from 'react';
import * as THREE from 'three';

import type { ProjectRecord } from '../../api/client';
import { useTheme } from '../../design-system/theme';
import { useSelection } from '../../stores/selection';
import { traceStore, useSignalValue } from '../../stores/trace';
import type { Trace } from '../../stores/trace';
import { useTimeCursor } from '../../stores/timeCursor';
import { layoutMassing, temperatureHue } from './layout';
import type { Massing } from './layout';

/** Whether a WebGL context can be created at all; the canvas is skipped when not. */
function webglAvailable(): boolean {
  try {
    const canvas = document.createElement('canvas');
    return Boolean(canvas.getContext('webgl2') ?? canvas.getContext('webgl'));
  } catch {
    return false;
  }
}

function blockColor(item: Massing, temperature: number, dark: boolean): THREE.Color {
  if (item.tempSignal && !Number.isNaN(temperature)) return new THREE.Color().setHSL(temperatureHue(temperature, item.tempUnit) / 360, 0.6, dark ? 0.55 : 0.6);
  if (item.status === 'approved') return new THREE.Color(dark ? '#4fc98a' : '#2f9a63');
  if (item.status === 'failed') return new THREE.Color(dark ? '#e06060' : '#c23b3b');
  return new THREE.Color(dark ? '#6f7d99' : '#8a97b3');
}

/**
 * Schematic 3D massing of a project: one extruded block per equipment,
 * tinted by its zone or discharge temperature when the project trace carries
 * one, else by candidate status. Click selects the equipment everywhere.
 * Plain three.js inside one effect; loaded lazily and never on the critical
 * path.
 */
export function ZoneMassing({ project, trace }: { project: ProjectRecord; trace: Trace | undefined }) {
  const { resolved } = useTheme();
  const dark = resolved === 'dark';
  const host = useRef<HTMLDivElement>(null);
  const [available] = useState(webglAvailable);
  const [spinning, setSpinning] = useState(() => !window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const spinningRef = useRef(spinning);
  useEffect(() => {
    spinningRef.current = spinning;
  }, [spinning]);
  const items = useMemo(() => layoutMassing(project, trace), [project, trace]);
  const selected = useSelection((state) => state.blockIds);
  const focus = items.find((item) => selected.has(item.name));
  const focusTemperature = useSignalValue(focus?.tempSignal ?? null);

  useEffect(() => {
    const element = host.current;
    if (!element || !available) return;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(1.5, window.devicePixelRatio));
    element.appendChild(renderer.domElement);
    renderer.domElement.style.display = 'block';
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 100);
    camera.position.set(0, 9, 12);
    camera.lookAt(0, 0.5, 0);
    scene.add(new THREE.AmbientLight(0xffffff, dark ? 0.7 : 0.9));
    const sun = new THREE.DirectionalLight(0xffffff, dark ? 1.1 : 1.3);
    sun.position.set(6, 10, 4);
    scene.add(sun);
    const depth = Math.max(1, ...items.map((item) => item.z));
    const group = new THREE.Group();
    group.position.z = -depth / 2;
    scene.add(group);
    const grid = new THREE.GridHelper(24, 24, dark ? 0x3a4052 : 0xc8cdd8, dark ? 0x262b38 : 0xe3e6ec);
    grid.position.z = depth / 2;
    group.add(grid);

    const meshes = new Map<string, THREE.Mesh<THREE.BoxGeometry, THREE.MeshStandardMaterial>>();
    const rings = new Map<string, THREE.Mesh>();
    for (const item of items) {
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(item.w, item.h, item.d), new THREE.MeshStandardMaterial({ color: blockColor(item, Number.NaN, dark), roughness: 0.7, metalness: 0.05 }));
      mesh.position.set(item.x, item.h / 2, item.z);
      mesh.userData.name = item.name;
      group.add(mesh);
      meshes.set(item.name, mesh);
      const radius = Math.max(item.w, item.d) * 0.7;
      const ring = new THREE.Mesh(new THREE.RingGeometry(radius, radius + 0.08, 48), new THREE.MeshBasicMaterial({ color: dark ? 0x8be9e0 : 0x1f7d8c, side: THREE.DoubleSide }));
      ring.rotation.x = -Math.PI / 2;
      ring.position.set(item.x, 0.01, item.z);
      ring.visible = false;
      group.add(ring);
      rings.set(item.name, ring);
    }

    // Live tint and selection are read straight from the stores each frame.
    const tint = () => {
      const { traceId, index } = useTimeCursor.getState();
      const chosen = useSelection.getState().blockIds;
      for (const item of items) {
        const mesh = meshes.get(item.name)!;
        const value = item.tempSignal && traceId ? traceStore.valueAt(traceId, item.tempSignal, index) : Number.NaN;
        mesh.material.color.copy(blockColor(item, value, dark));
        const isSelected = chosen.has(item.name);
        mesh.material.emissive.copy(isSelected ? mesh.material.color : new THREE.Color(0x000000));
        mesh.material.emissiveIntensity = isSelected ? 0.35 : 0;
        rings.get(item.name)!.visible = isSelected;
      }
    };

    const resize = () => {
      const width = element.clientWidth || 600;
      const height = element.clientHeight || 320;
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(element);

    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    const onClick = (event: MouseEvent) => {
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
      raycaster.setFromCamera(pointer, camera);
      const hit = raycaster.intersectObjects([...meshes.values()], false)[0];
      useSelection.getState().selectBlocks(hit ? [hit.object.userData.name as string] : []);
    };
    renderer.domElement.addEventListener('click', onClick);

    let frame = 0;
    let last = performance.now();
    const loop = (now: number) => {
      const delta = (now - last) / 1000;
      last = now;
      if (spinningRef.current) group.rotation.y += delta * 0.15;
      tint();
      renderer.render(scene, camera);
      frame = requestAnimationFrame(loop);
    };
    frame = requestAnimationFrame(loop);

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      renderer.domElement.removeEventListener('click', onClick);
      for (const mesh of meshes.values()) {
        mesh.geometry.dispose();
        mesh.material.dispose();
      }
      for (const ring of rings.values()) {
        ring.geometry.dispose();
        (ring.material as THREE.Material).dispose();
      }
      grid.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [items, dark, available]);

  if (!available) {
    return (
      <p role="status" className="px-4 py-3 text-sm text-fg-2" data-testid="massing-fallback">
        3D massing needs WebGL, which this browser does not provide. The system map above carries the same equipment and bindings.
      </p>
    );
  }

  return (
    <div className="flex flex-col" data-testid="massing">
      <div className="h-80 relative">
        <div ref={host} className="absolute inset-0" role="img" aria-label={`Zone massing of ${items.length} equipment`} />
        <button type="button" className="absolute right-3 top-3 raised px-2 h-7 text-2xs text-fg-1" onClick={() => setSpinning(!spinning)} aria-pressed={spinning}>
          {spinning ? 'Pause rotation' : 'Rotate'}
        </button>
      </div>
      <div className="px-4 py-2 flex items-center gap-3 text-xs hairline-t min-h-9">
        {focus ? (
          <>
            <span className="text-fg-0 font-medium">{focus.name}</span>
            <span className="text-fg-2 truncate">{focus.brick ?? 'no Brick class'}</span>
            {focus.tempSignal && (
              <span className="num text-fg-1">
                {Number.isNaN(focusTemperature) ? '—' : focusTemperature.toFixed(1)} {focus.tempUnit}
              </span>
            )}
            <span className="text-fg-2">{focus.status.replaceAll('_', ' ')}</span>
          </>
        ) : (
          <span className="text-fg-2">Click a block to select its equipment. Tint follows the zone temperature on the clock; without one, the candidate status.</span>
        )}
      </div>
    </div>
  );
}
