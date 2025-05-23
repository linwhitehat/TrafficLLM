from transformers import AutoModel, AutoTokenizer, AutoConfig
import streamlit as st
import torch
import json
import os

os.environ["CUDA_VISIBLE_DEVICES"] = '4'

with open("config.json", "r", encoding="utf-8") as fin:
    config = json.load(fin)

st.set_page_config(
    page_title="TrafficLLM Demo",
    page_icon=":robot:",
    layout='wide'
)


def load_model(model, ptuning_path):
    if ptuning_path is not None:
        prefix_state_dict = torch.load(
            os.path.join(ptuning_path, "pytorch_model.bin"))
        new_prefix_state_dict = {}
        for k, v in prefix_state_dict.items():
            if k.startswith("transformer.prefix_encoder."):
                new_prefix_state_dict[k[len("transformer.prefix_encoder."):]] = v
        model.transformer.prefix_encoder.load_state_dict(new_prefix_state_dict)

        model = model.half().cuda()
        model.transformer.prefix_encoder.float()

    return model


def preprompt(task, traffic_data):
    """Preprompts in LLMs for downstream traffic pattern learning"""
    prepromt_set = {
        "MTD": "Given the following traffic data <packet> that contains protocol fields, traffic features, and "
               "payloads. Please conduct the ENCRYPTED MALWARE DETECTION TASK to determine which application "
               "category the encrypted beign or malicious traffic belongs to. The categories include 'BitTorrent, "
               "FTP, Facetime, Gmail, MySQL, Outlook, SMB, Skype, Weibo, WorldOfWarcraft,Cridex, Geodo, Htbot, Miuref, "
               "Neris, Nsis-ay, Shifu, Tinba, Virut, Zeus'.\n",
        "BND": "Given the following traffic data <packet> that contains protocol fields, traffic features, "
               "and payloads. Please conduct the BOTNET DETECTION TASK to determine which type of network the "
               "traffic belongs to. The categories include 'IRC, Neris, RBot, Virut, normal'.\n",
        "WAD": "Classify the given HTTP request into normal and abnormal categories. Each HTTP request will consist "
               "of three parts: method, URL, and body, presented in JSON format. If a web attack is detected in an "
               "HTTP request, please output an 'exception'. Only output 'abnormal' or 'normal', no additional output "
               "is required. The given HTTP request is as follows:\n",
        "AAD": "Classify the given HTTP request into normal and abnormal categories. Each HTTP request will consist "
               "of three parts: method, URL, and body, presented in JSON format. If a web attack is detected in an "
               "HTTP request, please output an 'exception'. Only output 'abnormal' or 'normal', no additional output "
               "is required. The given HTTP request is as follows:\n",
        "EVD": "Given the following traffic data <packet> that contains protocol fields, traffic features, "
               "and payloads. Please conduct the encrypted VPN detection task to determine which behavior or "
               "application category the VPN encrypted traffic belongs to. The categories include 'aim, bittorrent, "
               "email, facebook, ftps, hangout, icq, netflix, sftp, skype, spotify, vimeo, voipbuster, youtube'.\n",
        "TBD": "Given the following traffic data <packet> that contains protocol fields, traffic features, and "
               "payloads. Please conduct the TOR BEHAVIOR DETECTION TASK to determine which behavior or application "
               "category the traffic belongs to under the Tor network. The categories include 'audio, browsing, chat, "
               "file, mail, p2p, video, voip'.\n"
    }

    prompt = prepromt_set[task] + traffic_data

    return prompt


def load_pcap(pcap_file):
    build_data = []
    tmp_path = "tmp.txt"

    fields = ["frame.encap_type", "frame.time", "frame.offset_shift", "frame.time_epoch", "frame.time_delta",
              "frame.time_relative", "frame.number", "frame.len", "frame.marked", "frame.protocols", "eth.dst",
              "eth.dst_resolved", "eth.src", "eth.src_resolved", "eth.type",
              "ip.version", "ip.hdr_len", "ip.dsfield", "ip.dsfield.dscp", "ip.dsfield.ecn", "ip.len", "ip.id",
              "ip.flags", "ip.flags.rb", "ip.flags.df", "ip.flags.mf", "ip.frag_offset", "ip.ttl", "ip.proto",
              "ip.checksum", "ip.checksum.status", "tcp.srcport", "tcp.dstport", "tcp.stream",
              "tcp.len", "tcp.seq", "tcp.nxtseq", "tcp.ack", "tcp.hdr_len", "tcp.flags",
              "tcp.flags.res", "tcp.flags.ns", "tcp.flags.cwr", "tcp.flags.ecn", "tcp.flags.urg", "tcp.flags.ack",
              "tcp.flags.push", "tcp.flags.reset", "tcp.flags.syn", "tcp.flags.fin", "tcp.flags.str",
              "tcp.window_size", "tcp.window_size_scalefactor", "tcp.checksum", "tcp.checksum.status",
              "tcp.urgent_pointer",
              "tcp.time_relative", "tcp.time_delta", "tcp.analysis.bytes_in_flight", "tcp.analysis.push_bytes_sent",
              "tcp.segment",
              "tcp.segment.count", "tcp.reassembled.length", "tcp.payload", "udp.srcport", "udp.dstport", "udp.length",
              "udp.checksum", "udp.checksum.status", "udp.stream", "data.len"]

    extract_str = " -e " + " -e ".join(fields) + " "
    cmd = "tshark -r " + pcap_file + extract_str + "-T fields -Y 'tcp or udp' > " + tmp_path
    os.system(cmd)

    with open(tmp_path, "r", encoding="utf-8") as fin:
        lines = fin.readlines()
    for line in lines:
        packet_data = ""
        values = line[:-1].split("\t")

        packet_data += fields[0] + ": " + values[0]
        for field, value in zip(fields[1:], values[1:]):
            if field == "tcp.flags.str":
                value = value.encode("unicode_escape").decode("unicode_escape")
            if field == "tcp.payload":
                value = value[:1000] if len(value) > 1000 else value
            if value == "":
                continue
            packet_data += ", "
            packet_data += field + ": " + value

        build_data.append(packet_data)

    return build_data[0]


def dual_stage_inference(human_instruction, traffic_data, model):

    # Stage 1: task understanding
    ptuning_path = os.path.join(config["peft_path"], config["peft_set"]["NLP"])
    model_nlp = load_model(model, ptuning_path)

    model_nlp = model_nlp.eval()

    task_response, history = model_nlp.chat(tokenizer, human_instruction, history=[])
    print("Downstream task: " + task_response)

    # Stage 2: task-specific traffic learning
    task = config["tasks"][task_response]
    ptuning_path = os.path.join(config["peft_path"], config["peft_set"][task])
    model_downstream = load_model(model, ptuning_path)

    model_downstream = model_downstream.eval()

    traffic_prompt = preprompt(task, traffic_data)
    final_response, history = model_downstream.chat(tokenizer, traffic_prompt, history=[],
                                                    max_length=max_length, top_p=top_p, temperature=temperature)
    print("Predicted result: " + final_response)

    return task_response, final_response


@st.cache_resource
def get_model():
    tokenizer = AutoTokenizer.from_pretrained(config["model_path"], trust_remote_code=True)
    model_config = AutoConfig.from_pretrained(config["model_path"], trust_remote_code=True, pre_seq_len=128)
    model = AutoModel.from_pretrained(config["model_path"], config=model_config, trust_remote_code=True)

    return tokenizer, model


tokenizer, model = get_model()


st.title("Chat with TrafficLLM")

max_length = st.sidebar.slider(
    'max_length', 0, 32768, 8192, step=1
)
top_p = st.sidebar.slider(
    'top_p', 0.0, 1.0, 0.8, step=0.01
)
temperature = st.sidebar.slider(
    'temperature', 0.0, 1.0, 0.8, step=0.01
)

if 'history' not in st.session_state:
    st.session_state.history = []

if 'past_key_values' not in st.session_state:
    st.session_state.past_key_values = None

for i, (query, response) in enumerate(st.session_state.history):
    with st.chat_message(name="user", avatar="user"):
        st.markdown(query)
    with st.chat_message(name="assistant", avatar="assistant"):
        st.markdown(response)
with st.chat_message(name="user", avatar="user"):
    input_placeholder = st.empty()
with st.chat_message(name="assistant", avatar="assistant"):
    message_placeholder = st.empty()

human_instruction = st.text_area(label="User Instruction",
                           height=100,
                           placeholder="Please enter your instruction to describe which "
                                       "traffic analysis task to conduct here.")

# traffic_data = st.text_area(label="Traffic Data",
#                            height=200,
#                            placeholder="Please enter the traffic features extracted from TrafficLLM's preprocessing "
#                                        "codes here. Start with <packet> indicator except for WAD and AAD tasks.")

traffic_data = ""

uploaded_file = st.file_uploader("Please upload the PCAP file.", type=None)

if uploaded_file is not None:

    save_path = f"./test.pcap"

    progress_bar = st.progress(0)

    chunk_size = 1024 * 1024
    bytes_written = 0

    with open(save_path, "wb") as f:
        while True:
            file_chunk = uploaded_file.read(chunk_size)
            if not file_chunk:
                break

            f.write(file_chunk)
            bytes_written += len(file_chunk)

            progress_percent = bytes_written / uploaded_file.size
            progress_bar.progress(progress_percent)

    traffic_data = load_pcap(save_path)

    st.success(f"The PCAP file has been uploaded.")

button = st.button("Submit", key="predict")

if button:

    input_placeholder.markdown("**Human instruction:** %s **Traffic data:** %s."
                               % (human_instruction if human_instruction != "" else "None.",
                                  traffic_data if traffic_data != "" else "None"))

    print("Human instruction: " + human_instruction)
    print("Traffic data: " + traffic_data)

    if human_instruction == "":
        message_placeholder.markdown("`User Instruction` cannot be empty. Please input your instruction.")

    if traffic_data == "":
        message_placeholder.markdown("`Traffic Data` cannot be empty. Please input the traffic data.")

    if human_instruction == "" and traffic_data == "":
        message_placeholder.markdown("`User Instruction` and `Traffic Data` cannot be empty. Please input your instruction and traffic data.")

    if human_instruction != "" and traffic_data != "":

        task_response, final_response = dual_stage_inference(human_instruction, traffic_data, model)
        message_placeholder.markdown("**Downstream task:** %s. **Predicted result:** %s." % (task_response, final_response))
