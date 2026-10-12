import * as THREE from 'three';
import { latLonXYZ } from './globeMath';

/** `latLonXYZ` as a three.js vector (this module is only imported by the lazy WebGL chunk). */
export const latLonToVec = (lat: number, lon: number, r = 1) => new THREE.Vector3(...latLonXYZ(lat, lon, r));
