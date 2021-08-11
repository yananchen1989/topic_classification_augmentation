import torch
import wandb
import time
import os
from tqdm import tqdm
import numpy as np
import pandas as pd
import random 
#import matplotlib.pyplot as plt
tqdm.pandas()

from transformers import GPT2Tokenizer
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from trl.gpt2 import GPT2HeadWithValueModel, respond_to_batch
from trl.ppo import PPOTrainer
from trl.core import build_bert_batch_from_txt


config = {
    "lm_name": "lvwerra/gpt2-imdb",
    "ref_lm_name": "lvwerra/gpt2-imdb",
    "cls_model_name": "lvwerra/bert-imdb",
    "tk_name": "gpt2",
    "steps": 51200,
    "batch_size": 64,
    "forward_batch_size": 16,
    "ppo_epochs": 4,   
    "txt_in_len": 5,
    "txt_out_len": 20,
    "lr": 1.41e-5,
    "init_kl_coef":0.2,
    "target": 6,
    "horizon":10000,
    "gamma":1,
    "lam":0.95,
    "cliprange": .2,
    "cliprange_value":.2,
    "vf_coef":.1, 
    "seed": 1,
}

wandb.init(name='long-response', project='gpt2-ctrl', config=config)

sentiment_model = AutoModelForSequenceClassification.from_pretrained(config["cls_model_name"], cache_dir="./cache_gpt_imdb_trl", local_files_only=True)
sentiment_tokenizer = AutoTokenizer.from_pretrained(config["cls_model_name"],cache_dir="./cache_gpt_imdb_trl", local_files_only=True)

gpt2_model = GPT2HeadWithValueModel.from_pretrained(config['lm_name'], cache_dir="./cache_gpt_imdb_trl", local_files_only=True)
gpt2_model_ref = GPT2HeadWithValueModel.from_pretrained(config['ref_lm_name'], cache_dir="./cache_gpt_imdb_trl", local_files_only=True)
gpt2_tokenizer = GPT2Tokenizer.from_pretrained(config['tk_name'], cache_dir="./cache_gpt_imdb_trl", local_files_only=True)
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

gpt2_model.to(device)
sentiment_model.to(device)
gpt2_model_ref.to(device)

wandb.watch(gpt2_model, log='all')

from utils.load_data import * 
dsn = 'imdb'
ds = load_data(dataset=dsn, samplecnt= 1024)


ds.df_train['tokens'] = ds.df_train['content'].progress_apply(lambda x: gpt2_tokenizer.encode(' '+x, return_tensors="pt").to(device)[0, :config['txt_in_len']])
ds.df_train['query'] = ds.df_train['tokens'].progress_apply(lambda x: gpt2_tokenizer.decode(x))


ctrl_str = ['[negative]', '[neutral]', '[positive]']

ctrl_tokens = dict((s, gpt2_tokenizer.encode(s, return_tensors="pt").squeeze().to(device)) for s in ctrl_str)


def pos_logit_to_reward(logit, task):
    """
    Take the positive sentiment logit and scale it for the task.
        task [negative]: reward = -logit
        task [neutral]: reward = -2*abs(logit)+4
        task [positive]: reward = logit
    """
    for i in range(len(logit)):
        if task[i]=='[negative]':
            logit[i] = -logit[i]
        elif task[i]=='[neutral]':
            logit[i] = -2*torch.abs(logit[i])+4
        elif task[i]=='[positive]':
            pass
        else:
            raise ValueError('task has to be in [0, 1, 2]!')
    return logit


ppo_trainer = PPOTrainer(gpt2_model, gpt2_model_ref, **config)
fbs = config['forward_batch_size']

for epoch in tqdm(range(int(np.ceil(config["steps"]/config['batch_size'])))):
    torch.cuda.empty_cache()
    logs = dict()
    game_data = dict()
    timing = dict()
    t0 = time.time()
    
    #### get a batch from the dataset and annotate tasks
    df_batch = ds.df_train.sample(config['batch_size'])
    task_list = random.choices(ctrl_str, k=config['batch_size'])
    task_tensors = torch.stack([ctrl_tokens[t] for t in task_list])
    query_list = df_batch['query'].tolist()
    game_data['query'] = [t+q for t,q in zip(task_list, query_list)]
    
    query_tensors = torch.stack(df_batch['tokens'].tolist())
    query_tensors = torch.cat((task_tensors, query_tensors), axis=1)
    
    #### get response from gpt2
    t = time.time()
    # response_tensors = []
    # for i in range(int(config['batch_size']/fbs)):
    #     response  = respond_to_batch(gpt2_model, query_tensors[i*fbs:(i+1)*fbs],
    #                                  txt_len=config['txt_out_len'])
    #     response_tensors.append(response)
    # response_tensors = torch.cat(response_tensors)

    response_tensors = respond_to_batch(gpt2_model, query_tensors, txt_len=config['txt_out_len'])

    game_data['response'] = [gpt2_tokenizer.decode(response_tensors[i, :]) for i in range(config['batch_size'])]
    timing['time/get_response'] = time.time()-t

    #### tokenize text for sentiment analysis
    t = time.time()
    texts = [q + r for q,r in zip(query_list, game_data['response'])]
    sentiment_inputs, attention_masks = build_bert_batch_from_txt(texts, sentiment_tokenizer, device)    
    timing['time/build_input_sentiment'] = time.time()-t

    #### get sentiment score
    t = time.time()
    pos_logits = []
    for i in range(int(config['batch_size']/fbs)):
        res = sentiment_model.forward(sentiment_inputs[i*fbs:(i+1)*fbs],
                                      attention_masks[i*fbs:(i+1)*fbs])[0][:, 1].detach()
        pos_logits.append(res)
    rewards = pos_logit_to_reward(torch.cat(pos_logits), task_list)
    timing['time/get_sentiment_preds'] = time.time()-t

    #### Run PPO training 
    t = time.time()
    stats = ppo_trainer.step(query_tensors, response_tensors, rewards)
    timing['time/optimization'] = time.time()-t
     
    #### Log everything
    timing['time/epoch'] = time.time()-t0
    table_rows = [list(r) for r in zip(game_data['query'], game_data['response'], rewards.cpu().tolist())]
    logs.update({'game_log':wandb.Table(
        columns=['query', 'response', 'reward'],
        rows=table_rows)})
    logs.update(timing)
    logs.update(stats)
    logs['env/reward_mean'] = torch.mean(rewards).cpu().numpy()
    logs['env/reward_std'] = torch.std(rewards).cpu().numpy()
    logs['env/reward_dist'] = rewards.cpu().numpy()
    for ctrl_s in ctrl_str:
        key = 'env/reward_'+ctrl_s.strip('[]')
        logs[key] = np.mean([r for r, t in zip(logs['env/reward_dist'], task_list) if t==ctrl_s])
    wandb.log(logs)





gpt2_model.save_pretrained('gpt2-imdb-ctrl')
#gpt2_tokenizer.save_pretrained('gpt2-imdb-ctrl')



input_string = '[negative] The movie'
input_tokens = gpt2_tokenizer.encode(input_string, return_tensors="pt").to(device)

response_tensors = respond_to_batch(gpt2_model, input_tokens, txt_len=config['txt_out_len'])
response_strings = gpt2_tokenizer.decode(response_tensors[0, :])
response_strings

