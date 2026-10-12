import * as THREE from 'three';

/** Soft halo just outside the limb (a back-faced shell). Shared by both looks, each with its own colour and reach. */
export function createHalo(opts: {
  color: THREE.Color;
  strength: number;
  sun: THREE.Vector3;
  /** additive light reads as glow on a dark canvas; on ivory it would wash out, so blend normally there */
  additive: boolean;
  /** how far the halo reaches in from its outer edge (0..1 of the facing term) */
  reach?: number;
  /** share of the halo that stays on the shaded side */
  nightFloor?: number;
}) {
  const mat = new THREE.ShaderMaterial({
    uniforms: {
      uColor: { value: opts.color },
      uSun: { value: opts.sun },
      uStrength: { value: opts.strength },
      uReach: { value: opts.reach ?? 0.42 },
      uFloor: { value: opts.nightFloor ?? 0.15 },
    },
    vertexShader: `
      varying vec3 vN; varying vec3 vView;
      void main(){ vN = normalize(normalMatrix * normal); vec4 mv = modelViewMatrix * vec4(position,1.0); vView = normalize(-mv.xyz); gl_Position = projectionMatrix * mv; }`,
    fragmentShader: `
      uniform vec3 uColor; uniform vec3 uSun; uniform float uStrength; uniform float uReach; uniform float uFloor; varying vec3 vN; varying vec3 vView;
      void main(){
        // back faces: -dot is 0 at the halo's outer edge and peaks at the globe's silhouette
        float k = clamp(-dot(normalize(vN), normalize(vView)) / uReach, 0.0, 1.0);
        float day = uFloor + (1.0 - uFloor) * smoothstep(-0.3, 0.6, dot(normalize(vN), uSun)); // outward normal: sun-side rim glows
        gl_FragColor = vec4(uColor, pow(k, 3.0) * uStrength * day);
      }`,
    side: THREE.BackSide,
    blending: opts.additive ? THREE.AdditiveBlending : THREE.NormalBlending,
    transparent: true,
    depthWrite: false,
  });
  return new THREE.Mesh(new THREE.SphereGeometry(1.1, 48, 48), mat);
}
