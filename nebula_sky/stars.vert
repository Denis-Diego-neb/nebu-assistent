attribute vec3 aPosition;
attribute vec3 aProperties;
varying vec3 vColor;
varying float vAlpha;
void main() {
  vec3 delta=aPosition-uCamera;
  vec3 local=vec3(dot(delta,uRotation[0]),dot(delta,uRotation[1]),dot(delta,uRotation[2]));
  float z=max(local.z,0.05),aspect=uResolution.x/uResolution.y;
  gl_Position=vec4(local.x/(FOV_TAN*aspect),local.y/FOV_TAN,0.0,z);
  float distanceToStar=length(delta),optical=0.0;
  vec3 ray=delta/max(distanceToStar,0.01);
  float span=min(distanceToStar,11.8);
#ifndef SEM_TEXTURA_NO_VERTICE
  // Estrelas atras do gas escurecem. Exige ler textura no vertex shader, que
  // e opcional em OpenGL ES 2.0; sem isso elas so ficam sempre acesas.
  for(int i=0;i<10;i++) {
    float t=span*(float(i)+0.5)/10.0;
    optical+=density(uCamera+ray*t)*smoothstep(0.1,0.8,t)*(1.0-smoothstep(9.0,11.8,t))*span/10.0;
  }
#endif
  float twinkle=0.86+0.14*sin(uTime*(0.45+aProperties.y*0.4)+aProperties.y*24.0);
  float edge=smoothstep(0.1,0.9,local.z);
  vAlpha=exp(-optical*1.7)*twinkle*edge*aProperties.z;
  vColor=mix(vec3(0.66,0.79,1.0),vec3(1.0,0.78,0.87),aProperties.y);
  gl_PointSize=clamp(aProperties.x*uResolution.y/(max(distanceToStar,1.0)*105.0),3.2,17.0);
}
