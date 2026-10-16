import { useEffect, useRef } from 'react';
import { SCENE_CSS, sceneMarkup, countUp } from './authScenes';

/**
 * The illustrated background. It lives in a shadow root so the scene's own class names
 * (.dk, .pp, .big, .bub ...) can never collide with the app's styles, and vice versa.
 * `role` is 'talent' | 'ent'; `index` is the chapter currently on screen.
 */
export default function StoryStage({ role, index, tint }) {
  const hostRef = useRef(null);
  const stageRef = useRef(null);

  // Build the shadow root once.
  useEffect(() => {
    const host = hostRef.current;
    if (!host || stageRef.current) return;
    const root = host.shadowRoot || host.attachShadow({ mode: 'open' });
    root.innerHTML = `<style>${SCENE_CSS}</style><div class="stage" aria-hidden="true"><div class="shade"></div></div>`;
    stageRef.current = root.querySelector('.stage');
  }, []);

  // Swap the scenes when the audience changes.
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    stage.querySelectorAll('.scn').forEach((n) => n.remove());
    stage.insertAdjacentHTML('afterbegin', sceneMarkup(role));
  }, [role]);

  // Show the current chapter.
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    stage.querySelectorAll('.scn').forEach((n, k) => n.classList.toggle('on', k === index));
    stage.querySelectorAll('.scn.on [data-count]').forEach(countUp);
  }, [role, index]);

  return <div ref={hostRef} className="as-stage-host" style={{ '--tint': tint }} aria-hidden="true" />;
}
