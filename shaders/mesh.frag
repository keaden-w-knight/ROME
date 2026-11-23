#version 450

const int MAX_LIGHTS = 8;

struct Light {
    vec4 position;   // xyz world position, w = type (0 dir, 1 point, 2 spot)
    vec4 direction;  // xyz axis (directional/spot), w = range
    vec4 color;      // rgb colour, w = intensity
    vec4 cone;       // x = cos(inner), y = cos(outer)
};

layout(set = 0, binding = 0) uniform Frame {
    vec4 eye;       // xyz camera position, w = ambient
    vec4 material;  // x = specular strength, y = shininess
    ivec4 counts;   // x = active light count
    Light lights[MAX_LIGHTS];
} frame;

layout(location = 0) in vec3 v_normal;
layout(location = 1) in vec3 v_color;
layout(location = 2) in vec3 v_worldpos;
layout(location = 0) out vec4 out_color;

void main() {
    vec3 n = normalize(v_normal);
    vec3 view = normalize(frame.eye.xyz - v_worldpos);

    vec3 lit = v_color * frame.eye.w;  // ambient fill

    int count = min(frame.counts.x, MAX_LIGHTS);
    for (int i = 0; i < count; ++i) {
        Light lt = frame.lights[i];
        int type = int(lt.position.w);

        vec3 l;
        float atten = 1.0;
        if (type == 0) {  // directional
            l = normalize(-lt.direction.xyz);
        } else {          // point / spot
            vec3 to_light = lt.position.xyz - v_worldpos;
            float dist = length(to_light);
            l = to_light / max(dist, 1e-4);
            float t = clamp(1.0 - dist / max(lt.direction.w, 1e-4), 0.0, 1.0);
            atten = t * t;
            if (type == 2) {  // spot cone falloff
                float cd = dot(-l, normalize(lt.direction.xyz));
                atten *= clamp((cd - lt.cone.y) / max(lt.cone.x - lt.cone.y, 1e-4), 0.0, 1.0);
            }
        }

        float energy = lt.color.w * atten;
        float diffuse = max(dot(n, l), 0.0) * energy;
        vec3 half_vec = normalize(l + view);
        float spec = pow(max(dot(n, half_vec), 0.0), max(frame.material.y, 1.0))
                     * frame.material.x * energy;

        lit += v_color * diffuse * lt.color.rgb + lt.color.rgb * spec;
    }

    out_color = vec4(min(lit, vec3(1.0)), 1.0);
}
