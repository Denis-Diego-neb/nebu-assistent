/* Persistent world-space nebula. No recycled billboards or per-frame spawning. */
(() => {
  'use strict';
  const COMMON = `
precision highp float;
uniform sampler2D uNoise;
uniform vec3 uCamera;
uniform mat3 uRotation;
uniform vec2 uResolution;
uniform float uTime;
// Deriva do gas, calculada na CPU. Dentro do raymarch sao ~80 avaliacoes de
// fbm por pixel; um sin() aqui custaria centenas por quadro sem precisar.
uniform vec3 uDrift;
uniform vec3 uShear;
// Shared lens for gas and stars: ~58 degrees vertically (was ~70).
const float FOV_TAN=0.55;
float noise3(vec3 p) {
  vec3 i=floor(p),f=fract(p); f=f*f*(3.0-2.0*f);
  vec2 uv=i.xy+vec2(37.0,17.0)*i.z+f.xy;
  vec2 rg=texture2D(uNoise,(uv+0.5)/256.0).rg;
  return mix(rg.x,rg.y,f.z);
}
float fbm(vec3 p) {
  // E o cisalhamento entre as camadas que faz o gas parecer vivo; deslocar o
  // conjunto junto so pareceria camera se mexendo.
  return noise3(p+uDrift)*0.53+noise3(p*2.03+13.7-uShear)*0.27+
         noise3(p*4.11+29.1+uShear.zxy*1.7)*0.13+noise3(p*8.21+7.5-uDrift.yzx*2.3)*0.07;
}
float density(vec3 p) {
  vec3 q=p*1.04+vec3(5.4,8.1,3.7);
  float bend=noise3(q*0.43+uDrift*0.62)*1.35;
  float n=fbm(q+vec3(bend,-bend*0.6,bend*0.35));
  float billow=smoothstep(0.63,0.84,n);
  float channel=0.12+0.88*smoothstep(0.27,1.9,abs(p.x+0.48*sin(p.z*0.62)));
  return pow(billow,1.78)*channel*0.82;
}
vec3 pigment(vec3 p) {
  float region=0.5+0.5*sin(p.x*0.27+p.y*0.15+p.z*0.10+fbm(p*0.12)*2.0);
  float pockets=fbm(p*0.19+vec3(17.2,31.8,9.4));
  vec3 blue=vec3(0.035,0.22,1.0);
  vec3 violet=vec3(0.34,0.055,0.96);
  vec3 lilac=vec3(0.68,0.22,1.0);
  vec3 pink=vec3(1.0,0.09,0.57);
  vec3 red=vec3(1.0,0.025,0.075);
  vec3 color=mix(blue,violet,smoothstep(0.06,0.36,region));
  color=mix(color,pink,smoothstep(0.32,0.68,region));
  color=mix(color,red,smoothstep(0.64,0.96,region));
  color=mix(color,lilac,smoothstep(0.52,0.80,pockets)*0.28);
  return color;
}
`;
  const QUAD_VERTEX = `attribute vec2 aPosition;void main(){gl_Position=vec4(aPosition,0.0,1.0);}`;
  const VOLUME_FRAGMENT = COMMON + `
void main() {
  vec2 uv=(gl_FragCoord.xy*2.0-uResolution)/uResolution.y;
  vec3 ray=uRotation*normalize(vec3(uv*FOV_TAN,1.0));
  vec3 color=vec3(0.0);float transmission=1.0;
  for(int i=0;i<40;i++) {
    float t=0.20+(float(i)+0.5)*0.29;
    vec3 p=uCamera+ray*t;
    float d=density(p)*smoothstep(0.1,0.8,t)*(1.0-smoothstep(9.0,11.8,t));
    if(d>0.008) {
      float shadow=exp(-density(p+vec3(-0.35,0.48,-0.23))*3.8);
      float illumination=0.045+shadow*0.95;
      vec3 gas=pigment(p)*illumination;
      float rim=pow(max(0.0,1.0-d*2.5),3.0)*shadow;
      gas+=vec3(0.17,0.12,0.22)*rim*0.28;
      float alpha=1.0-exp(-d*0.29*1.15);
      color+=transmission*alpha*gas;
      transmission*=1.0-alpha;
    }
  }
  // Keep the UI's central reading area quieter, without modifying the world.
  vec2 screen=gl_FragCoord.xy/uResolution;
  float center=exp(-dot((screen-vec2(0.5,0.53))*vec2(3.5,5.0),(screen-vec2(0.5,0.53))*vec2(3.5,5.0)));
  color*=1.18-center*0.25;
  color=pow(max(color,vec3(0.0)),vec3(0.88));
  gl_FragColor=vec4(color,1.0);
}`;
  const STAR_VERTEX = COMMON + `
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
  for(int i=0;i<10;i++) {
    float t=span*(float(i)+0.5)/10.0;
    optical+=density(uCamera+ray*t)*smoothstep(0.1,0.8,t)*(1.0-smoothstep(9.0,11.8,t))*span/10.0;
  }
  float twinkle=0.86+0.14*sin(uTime*(0.45+aProperties.y*0.4)+aProperties.y*24.0);
  float edge=smoothstep(0.1,0.9,local.z);
  vAlpha=exp(-optical*1.7)*twinkle*edge*aProperties.z;
  vColor=mix(vec3(0.66,0.79,1.0),vec3(1.0,0.78,0.87),aProperties.y);
  gl_PointSize=clamp(aProperties.x*uResolution.y/(max(distanceToStar,1.0)*105.0),3.2,17.0);
}`;
  const STAR_FRAGMENT = `precision mediump float;varying vec3 vColor;varying float vAlpha;
void main(){float r=length(gl_PointCoord-0.5)*2.0;float core=exp(-r*r*32.0),halo=exp(-r*r*5.0)*0.19;float a=(core+halo)*(1.0-smoothstep(0.7,1.0,r))*vAlpha;gl_FragColor=vec4(vColor*a,a);}`;
  function seedRandom(seed) { return () => { seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296; }; }
  // Monotonic yaw: fixed world points move right on screen at every menu step.
  // Sine/cosine belong only in the rotation matrix, never around the yaw itself.
  function cameraPose(time,angle,sx,sy){
    const seconds=time/1000,yaw=-angle*.22+sx*.007,pitch=sy*.006;
    const cy=Math.cos(yaw),s=Math.sin(yaw),cp=Math.cos(pitch),sp=Math.sin(pitch);
    return {yaw,rotation:new Float32Array([cy,0,-s,s*sp,cp,cy*sp,s*cp,-sp,cy*cp]),
      camera:new Float32Array([sx*.024,sy*.022+Math.sin(seconds*.021)*.09,Math.sin(seconds*.016)*.35])};
  }
  // Senos de periodos incomensuraveis: a cena nunca repete de forma visivel e o
  // valor fica limitado, sem somar um tempo que cresce e perde precisao no
  // shader. Amplitude em larguras de feature do ruido; periodos de 30 a 100 s
  // dao movimento perceptivel em poucos segundos sem virar fervura.
  const DRIFT = [[0.18, 0.2110, 0.00, 0.11, 0.0873, 1.70],
                 [0.15, 0.1670, 2.30, 0.09, 0.1231, 0.40],
                 [0.20, 0.1390, 4.10, 0.10, 0.0977, 2.90]];
  const SHEAR = [[0.12, 0.0731, 0.90], [0.14, 0.0619, 3.40], [0.11, 0.0857, 1.90]];
  function gasFlow(seconds) {
    const drift = new Float32Array(3), shear = new Float32Array(3);
    for (let i = 0; i < 3; i++) {
      const [a1, w1, f1, a2, w2, f2] = DRIFT[i];
      drift[i] = a1 * Math.sin(w1 * seconds + f1) + a2 * Math.sin(w2 * seconds + f2);
      const [a, w, f] = SHEAR[i];
      shear[i] = a * Math.sin(w * seconds + f);
    }
    return { drift, shear };
  }
  function create(canvas) {
    const gl=canvas.getContext('webgl',{alpha:false,antialias:false,depth:false,powerPreference:'low-power',preserveDrawingBuffer:true});
    if(!gl) return null;
    let volume,stars,quad,starBuffer,texture,lost=false,width=0,height=0,lastFrame=null;
    const count=3200;
    function shader(type,source){const s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));return s;}
    function program(vs,fs){const p=gl.createProgram(),v=shader(gl.VERTEX_SHADER,vs),f=shader(gl.FRAGMENT_SHADER,fs);gl.attachShader(p,v);gl.attachShader(p,f);gl.linkProgram(p);gl.deleteShader(v);gl.deleteShader(f);if(!gl.getProgramParameter(p,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(p));return {p,u:Object.fromEntries(['uNoise','uCamera','uRotation','uResolution','uTime','uDrift','uShear'].map(n=>[n,gl.getUniformLocation(p,n)]))};}
    function init(){
      volume=program(QUAD_VERTEX,VOLUME_FRAGMENT);stars=program(STAR_VERTEX,STAR_FRAGMENT);
      quad=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,quad);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,-1,1,1,-1,1,1]),gl.STATIC_DRAW);
      const random=seedRandom(7331),base=new Uint8Array(256*256),pixels=new Uint8Array(256*256*4);
      for(let i=0;i<base.length;i++)base[i]=Math.floor(random()*256);
      for(let y=0;y<256;y++)for(let x=0;x<256;x++){const i=(y*256+x)*4;pixels[i]=base[y*256+x];pixels[i+1]=base[((y+17)%256)*256+(x+37)%256];pixels[i+3]=255;}
      texture=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,texture);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,256,256,0,gl.RGBA,gl.UNSIGNED_BYTE,pixels);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.REPEAT);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.REPEAT);
      const points=new Float32Array(count*6);
      for(let i=0;i<count;i++){const layer=i%3,radius=layer===0?2.6+random()*3.0:layer===1?6+random()*5:12+random()*11;const azimuth=random()*Math.PI*2,elevation=random()*2-1,ring=radius*Math.sqrt(1-elevation*elevation);points.set([Math.sin(azimuth)*ring,elevation*radius,Math.cos(azimuth)*ring,i%19===0?9:3+random()*3,random(),i%19===0?1.25:.65+random()*.4],i*6);}
      starBuffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,starBuffer);gl.bufferData(gl.ARRAY_BUFFER,points,gl.STATIC_DRAW);lost=false;
    }
    function resize(w,h){const ratio=Math.min(1,Math.sqrt(260000/(w*h)));const nw=Math.max(1,Math.round(w*ratio)),nh=Math.max(1,Math.round(h*ratio));if(nw!==width||nh!==height){width=nw;height=nh;canvas.width=width;canvas.height=height;}gl.viewport(0,0,width,height);}
    function uniforms(obj,camera,rotation,time,flow){gl.useProgram(obj.p);gl.uniform1i(obj.u.uNoise,0);gl.uniform3fv(obj.u.uCamera,camera);gl.uniformMatrix3fv(obj.u.uRotation,false,rotation);gl.uniform2f(obj.u.uResolution,width,height);gl.uniform1f(obj.u.uTime,time);gl.uniform3fv(obj.u.uDrift,flow.drift);gl.uniform3fv(obj.u.uShear,flow.shear);}
    function draw(time,angle,sx,sy,w,h){lastFrame=[time,angle,sx,sy,w,h];if(lost)return;resize(w,h);const seconds=time/1000;
      const {camera,rotation}=cameraPose(time,angle,sx,sy);const flow=gasFlow(seconds);
      gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,texture);gl.disable(gl.BLEND);uniforms(volume,camera,rotation,seconds,flow);
      gl.bindBuffer(gl.ARRAY_BUFFER,quad);const qp=gl.getAttribLocation(volume.p,'aPosition');gl.enableVertexAttribArray(qp);gl.vertexAttribPointer(qp,2,gl.FLOAT,false,0,0);gl.drawArrays(gl.TRIANGLES,0,6);gl.disableVertexAttribArray(qp);
      uniforms(stars,camera,rotation,seconds,flow);gl.bindBuffer(gl.ARRAY_BUFFER,starBuffer);const ap=gl.getAttribLocation(stars.p,'aPosition'),props=gl.getAttribLocation(stars.p,'aProperties');gl.enableVertexAttribArray(ap);gl.enableVertexAttribArray(props);gl.vertexAttribPointer(ap,3,gl.FLOAT,false,24,0);gl.vertexAttribPointer(props,3,gl.FLOAT,false,24,12);gl.enable(gl.BLEND);gl.blendFunc(gl.ONE,gl.ONE);gl.drawArrays(gl.POINTS,0,count);gl.disableVertexAttribArray(ap);gl.disableVertexAttribArray(props);gl.disable(gl.BLEND);
    }
    canvas.addEventListener('webglcontextlost',e=>{e.preventDefault();lost=true;});
    canvas.addEventListener('webglcontextrestored',()=>{try{init();if(lastFrame)draw(...lastFrame);}catch(e){console.warn('Nebula: não foi possível restaurar WebGL.',e);}});
    try{init();}catch(e){console.warn('Nebula: volume 3D indisponível.',e);return null;}
    return {draw,get lost(){return lost;}};
  }
  window.NebulaVolume={create,cameraPose,gasFlow};
})();
