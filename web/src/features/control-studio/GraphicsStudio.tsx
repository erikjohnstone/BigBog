import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Brush,
  CheckCircle2,
  CircleAlert,
  Eye,
  Layers3,
  Link2,
  MonitorCog,
  ShieldCheck,
} from 'lucide-react';

import { api, type GraphicsModel } from '../../api/client';

export function GraphicsStudio({ runId }: { runId: string }) {
  const model = useQuery({ queryKey: ['graphics-model', runId], queryFn: () => api.graphicsModel(runId) });
  const plan = useQuery({ queryKey: ['graphics-plan', runId], queryFn: () => api.graphicsPlan(runId) });
  const deliverables = useQuery({ queryKey: ['deliverables', runId], queryFn: () => api.deliverables(runId) });
  const [selectedView, setSelectedView] = useState<string | null>(null);

  if (model.isLoading || plan.isLoading || deliverables.isLoading) return <div className="graphics-state"><div className="studio-state-spinner" /><strong>Opening graphics model…</strong></div>;
  if (model.data?.state !== 'available') return <div className="graphics-state"><Brush size={28} /><strong>No declared graphics views</strong><span>Add graphics requirements or a contractor environment pack during intake.</span></div>;
  const graphics = model.data.data;
  const view = graphics.views.find((item) => item.id === selectedView) ?? graphics.views[0];
  const targetPlan = plan.data?.state === 'available' ? plan.data.data : null;
  const planView = targetPlan?.views.find((item) => item.id === view?.id);
  const blockers = deliverables.data?.state === 'available' ? deliverables.data.data.blocking_gates : [];

  return (
    <div className="graphics-studio">
      <section className="graphics-summary">
        <div className="graphics-summary-icon"><MonitorCog size={24} /></div>
        <div><span className="eyebrow">GRAPHICS STUDIO</span><h2>{graphics.equipment_name} operator experience</h2><p>Review point coverage, shop styling, bindings, and Niagara PX target status from the signed deliverable model.</p></div>
        <span className={graphics.all_declared_views_target_compiled ? 'graphics-target pass' : 'graphics-target blocked'}>{graphics.all_declared_views_target_compiled ? <CheckCircle2 size={15} /> : <CircleAlert size={15} />}{graphics.all_declared_views_target_compiled ? `${graphics.niagara_px_count} PX compiled` : 'PX target blocked'}</span>
      </section>
      <div className="graphics-layout">
        <aside aria-label="Graphics views" className="graphics-tree">
          <div className="pane-heading"><Layers3 size={16} /><strong>Declared views</strong></div>
          {graphics.views.map((item) => <button className={item.id === view?.id ? 'active' : ''} key={item.id} onClick={() => setSelectedView(item.id)} type="button"><Eye size={14} /><span><strong>{item.title}</strong><small>{item.widgets.length} bound widgets · {item.template}</small></span></button>)}
          <section><span className="eyebrow">SHOP PROFILE</span><strong>{graphics.shop_profile?.name ?? 'No shop profile'}</strong><small>{graphics.shop_profile?.graphics_theme ?? 'Default review-data theme'}</small>{graphics.shop_profile?.niagara_site_ord && <code>{graphics.shop_profile.niagara_site_ord}</code>}</section>
        </aside>
        <section className="graphics-canvas-panel">
          <header><div><span className="eyebrow">REVIEW PREVIEW</span><h2>{view?.title ?? 'No selected view'}</h2></div><span>Vendor-neutral engineering model</span></header>
          {view ? <EquipmentGraphic model={graphics} view={view} /> : <div className="graphics-empty">No declared view is available.</div>}
        </section>
        <aside aria-label="Graphics target inspector" className="graphics-inspector" tabIndex={0}>
          <div className="pane-heading"><ShieldCheck size={16} /><strong>Target readiness</strong></div>
          <div className={planView?.status === 'compiled' ? 'graphics-gate pass' : 'graphics-gate blocked'}>{planView?.status === 'compiled' ? <CheckCircle2 size={18} /> : <CircleAlert size={18} />}<span><strong>{planView?.status === 'compiled' ? 'Niagara PX emitted' : 'Template contract required'}</strong><small>{planView?.reason ?? targetPlan?.runtime_gate ?? graphics.blocker}</small></span></div>
          <InspectorSection icon={<Link2 size={14} />} label="Bindings">{view?.widgets.map((widget) => <div className="graphics-binding" key={widget.id}><span><strong>{widget.label}</strong><small>{widget.kind} · {widget.data_type}</small></span><code>{widget.bacnet ? `${widget.bacnet.device_instance}/${widget.bacnet.object_id}` : widget.id}</code></div>)}</InspectorSection>
          <InspectorSection icon={<ShieldCheck size={14} />} label="Safety contract">{targetPlan ? Object.entries(targetPlan.safety).map(([key, value]) => <div className="graphics-safety-row" key={key}><span>{key.replaceAll('_', ' ')}</span><strong className={value ? 'yes' : 'no'}>{value ? 'Yes' : 'No'}</strong></div>) : <span className="graphics-muted">No target plan retained.</span>}</InspectorSection>
          {blockers.filter((item) => /graphic|PX/i.test(item)).map((blocker) => <p className="graphics-blocker" key={blocker}>{blocker}</p>)}
        </aside>
      </div>
    </div>
  );
}

function EquipmentGraphic({ model, view }: { model: GraphicsModel; view: GraphicsModel['views'][number] }) {
  const placements = useMemo(() => {
    const xs = view.widgets.map((widget) => widget.layout_hint.x);
    const ys = view.widgets.map((widget) => widget.layout_hint.y);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    return view.widgets.map((widget) => ({
      widget,
      left: maxX === minX ? 50 : 5 + ((widget.layout_hint.x - minX) / (maxX - minX)) * 72,
      top: maxY === minY ? 42 : 10 + ((widget.layout_hint.y - minY) / (maxY - minY)) * 69,
    }));
  }, [view]);
  return (
    <div className="equipment-graphic" aria-label={`${view.title} graphics preview`}>
      <div className="graphic-topbar"><span>{model.site}</span><strong>{model.equipment_name}</strong><span>ENGINEERING PREVIEW</span></div>
      <div className="graphic-schematic" aria-hidden="true"><i className="duct-main" /><i className="duct-branch" /><span className="fan-symbol">FAN</span><span className="coil-symbol">COIL</span><span className="damper-symbol">DMP</span></div>
      {placements.map(({ widget, left, top }) => <div className={`graphic-widget ${widget.kind}`} key={widget.id} style={{ left: `${left}%`, top: `${top}%` }}><span>{widget.label}</span><strong>{widget.data_type === 'boolean' ? 'ON' : `--${widget.units ? ` ${widget.units}` : ''}`}</strong><small>{widget.id}</small></div>)}
      <footer><span>{model.shop_profile?.graphics_theme ?? 'BACTalk review theme'}</span><span>{view.navigation_parent ?? 'Equipment'} / {view.title}</span></footer>
    </div>
  );
}

function InspectorSection({ icon, label, children }: { icon: React.ReactNode; label: string; children: React.ReactNode }) {
  return <section className="graphics-inspector-section"><h3>{icon}{label}</h3>{children}</section>;
}
