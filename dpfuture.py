import argparse,os
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "2"

parser = argparse.ArgumentParser()
parser.add_argument("--dsn", default='uci', type=str)
parser.add_argument("--samplecnt", default=128, type=int)
parser.add_argument("--future_steps", default=64, type=int)
parser.add_argument("--test_beams", default=256, type=int)
parser.add_argument("--batch_size", default=32, type=int)
parser.add_argument("--candidates", default=64, type=int)
parser.add_argument("--cls_score_thres", default=0.8, type=float)
parser.add_argument("--max_aug_times", default=1, type=int)
parser.add_argument("--seed", default=0, type=int)
parser.add_argument("--gpu", default="3", type=str)
args = parser.parse_args()
print('args==>', args)

os.environ['CUDA_VISIBLE_DEVICES'] = args.gpu
import tensorflow as tf 
gpus = tf.config.experimental.list_physical_devices('GPU')
print('======>',gpus,'<=======')
if gpus:
  try:
    for gpu in gpus:
      tf.config.experimental.set_memory_growth(gpu, True)
      # tf.config.experimental.set_virtual_device_configuration(gpu, \
      #      [tf.config.experimental.VirtualDeviceConfiguration(memory_limit=1024)])
  except RuntimeError as e:
    print(e)

from transformers import top_k_top_p_filtering
from torch.nn import functional as F
import os,string,torch,math,time

from utils.load_data import * 
from utils.transblock import * 
ds = load_data(dataset=args.dsn, samplecnt= args.samplecnt)
ds, proper_len = process_ds(ds, 64)

ixl = {ii[0]:ii[1] for ii in ds.df_test[['label','label_name']].drop_duplicates().values}
ixl_rev = {ii[1]:ii[0] for ii in ds.df_test[['label','label_name']].drop_duplicates().values}
#seed = random.sample(list(range(10000)), 1)[0]

testbed_func = {"test":do_train_test_thread, "valid":do_train_test_valid_thread}


def thread_testing(testvalid, df_train, df_test):
    best_test_accs = []
    models = []

    for ddi in range(3):
        threads = []
        for di in range(1):
            t = Thread(target=testbed_func[testvalid], \
                        args=(df_train, df_test, best_test_accs, models, di + ddi*2, 100,  0))
            t.start()
            threads.append(t)

        # join all threads
        for t in threads:
            t.join()

    acc = round(np.array(best_test_accs).max(), 4)

    #model_best = models[np.array(best_test_accs).argmax()]
    return  acc



def remove_str(sent):
    rml = ['(AP)', '(Reuters)', '(Canadian Press)', '&lt;b&gt;...&lt;/b&gt', '(AFP)', '(washingtonpost.com)', \
                '(NewsFactor)', '(USATODAY.com)', '(Ziff Davis)', '#39;' ]
    for word in rml:
        sent = sent.replace(word,'')

    sent.replace(' #39;', "'")
    return sent.strip(string.punctuation).strip()

if args.dsn =='agt':
    ds.df_train['content'] = ds.df_train['content'].map(lambda x: remove_str(x))

# for ix, row in ds.df_train.iterrows():
#     print(row['label_name'])
#     print(row['content'], '\n')

ds.df_train['content'] = ds.df_train['content'].map(lambda x: x.strip(string.punctuation).strip())
#ds, proper_len = process_ds(ds, 32)


with tf.distribute.MirroredStrategy().scope():
    model_cls = get_model_bert(ds.df_test.label.unique().shape[0])
model_cls.load_weights("./model_cls/model_full_{}.h5".format(args.dsn))   


# gpt2
from transformers import pipeline

#if args.genm == 'gpt2':
from transformers import GPT2Tokenizer, GPT2LMHeadModel #TFGPT2LMHeadModel, TFGPT2Model, TFAutoModelForCausalLM
tokenizer_gpt2 = GPT2Tokenizer.from_pretrained('gpt2', cache_dir="./cache", local_files_only=True)
#tokenizer_gpt2.padding_side = "left" 
tokenizer_gpt2.pad_token = tokenizer_gpt2.eos_token # to avoid an error "<|endoftext|>": 50256
tokenizer_gpt2.sep_token = '<|sep|>'
#tokenizer_gpt2.add_tokens(tokenizer_gpt2.sep_token)
print(tokenizer_gpt2)
gpt2 = GPT2LMHeadModel.from_pretrained('gpt2', cache_dir="./cache", local_files_only=True)
gpt2.trainable = False
gpt2.config.pad_token_id = 50256
gen_nlp  = pipeline("text-generation", model=gpt2, tokenizer=tokenizer_gpt2, device=len(gpus)-1, return_full_text=False)


# elif args.genm == 't5':
from transformers import T5Tokenizer, AutoModelWithLMHead
tokenizer_t5 = T5Tokenizer.from_pretrained("t5-base", cache_dir="./cache", local_files_only=True)
print(tokenizer_t5)


t5 = AutoModelWithLMHead.from_pretrained("t5-base", cache_dir="./cache", local_files_only=True)

ft_model_path = 'ft_model_{}_{}'.format('t5', 'tc')
checkpoint_files = glob.glob(ft_model_path+"/checkpoint_loss_*")
list.sort(checkpoint_files)
t5 = AutoModelWithLMHead.from_pretrained(checkpoint_files[0])  


gen_nlp  = pipeline("text2text-generation", model=t5, tokenizer=tokenizer_t5, device=len(gpus)-1)

tokens_len_ori = tokenizer_t5.encode(sent, return_tensors="pt").shape[1]
result_ = gen_nlp([sent+tokenizer_t5.eos_token], max_length=64 , \
                                do_sample=True, top_p=0.9, top_k=0, temperature=1.2,\
                                repetition_penalty=1.2, num_return_sequences=32,\
                                clean_up_tokenization_spaces=True)




from threading import Thread
def gen_vs(sent, future_steps, test_beams, model_cls):
    tokens_len_ori = tokenizer_gpt2.encode(sent, return_tensors="pt").shape[1]
    result_ = gen_nlp([sent], max_length=tokens_len_ori + future_steps, \
                                do_sample=True, top_p=0.9, top_k=0, temperature=1,\
                                repetition_penalty=1.2, num_return_sequences=test_beams,\
                                clean_up_tokenization_spaces=True)
    x = np.array([ii['generated_text'] for ii in result_])
    y = np.array([label] * x.shape[0])
    eval_result_ori = model_cls.evaluate(x, y, batch_size=args.batch_size, verbose=0)    
    eval_result_oris.append(eval_result_ori[0])

def gengen_vs(sent, loss_ori, future_steps, candidates, test_beams, model_cls):
    tokens_len_ori = tokenizer_gpt2.encode(sent, return_tensors="pt").shape[1]
    result_0 = gen_nlp([sent], max_length=tokens_len_ori + future_steps, do_sample=True, top_p=0.9, top_k=0, temperature=1,\
                                repetition_penalty=1.2, num_return_sequences=candidates, clean_up_tokenization_spaces=True)
    #print("result_0 generated")
    result_1 = gen_nlp([ ii['generated_text'].strip().replace('\n',' ') for ii in result_0], max_length=future_steps+future_steps, \
                                  do_sample=True, top_p=0.9, top_k=0, temperature=1,\
                                repetition_penalty=1.2, num_return_sequences=test_beams, clean_up_tokenization_spaces=True)
    #print("result_1 generated")
    assert len(result_1) * len(result_1[0]) == candidates * test_beams

    all_results = []
    for r in result_1:
        all_results.extend( [ii['generated_text'] for ii in r] )

    assert len(all_results) == candidates * test_beams
  
    x = np.array(all_results)
    #y = np.array([label] * x.shape[0])
    preds = model_cls.predict(x,  batch_size=args.batch_size, verbose=0) 

    scores = []
    for j in range(0, len(all_results), test_beams):
        preds_j = preds[j:j+test_beams]
        y_j = np.array([label] * preds_j.shape[0])
        loss = tf.keras.losses.sparse_categorical_crossentropy(y_j, preds_j)
        loss_mean = loss.numpy().mean()
        score = loss_ori - loss_mean
        scores.append(score)
    
    # for i in range(len(result_1)): #  32 * 256
    #     x = np.array([ii['generated_text'] for ii in result_1[i]])
    #     y = np.array([label] * x.shape[0])
    #     eval_result = model_cls.evaluate(x, y, batch_size=args.batch_size, verbose=0) 
    #     print(eval_result[0])
    #     #print('\n' , result_0[i]['generated_text'])
    #     score = loss_ori - eval_result[0] 
    #     #print("loss_diff:", score)
    #     scores.append(score)

    df_future = pd.DataFrame(zip([ ii['generated_text'].strip().replace('\n', ' ') for ii in result_0], scores), \
                                        columns=['content','score'])
    df_future_ll.append(df_future)


infos = []
infos_rnd = []
arxivs = []
for ix, row in ds.df_train.sample(frac=1).reset_index().iterrows():
    print(ix, 'of', ds.df_train.shape[0])
    t0 = time.time()
    sent = row['content']
    label = row['label']
    label_name = row['label_name']
    torch.cuda.empty_cache()
    eval_result_oris = []
    threads = []
    for di in range(1):
        t = Thread(target=gen_vs, args=(sent, args.future_steps, args.test_beams, model_cls))
        t.start()
        threads.append(t)

    # join all threads
    for t in threads:
        t.join()

    loss_ori = sum(eval_result_oris) / len(eval_result_oris)
    print("eval_result_oris==>", eval_result_oris)

    torch.cuda.empty_cache()

    df_future_ll = []
    threads = []
    for di in range(1):
        t = Thread(target=gengen_vs, args=(sent, loss_ori, args.future_steps, args.candidates, args.test_beams, model_cls))
        t.start()
        threads.append(t)

    # join all threads
    for t in threads:
        t.join()

    df_future_threds = pd.concat(df_future_ll)

    df_future_threds.sort_values(by=['score'], ascending=False, inplace=True)
    #sents = df_future.head(8)['content'].tolist()

    preds = model_cls.predict(df_future_threds['content'].values, batch_size= args.batch_size, verbose=0)

    df_future_threds['cls_score'] = preds[:, label] 
    df_future_threds['cls_label'] = preds.argmax(axis=1)
    dfaug = df_future_threds.loc[(df_future_threds['cls_label']==label) & \
                                 (df_future_threds['cls_score']>=args.cls_score_thres)  & \
                                 (df_future_threds['score']>0)]

    
    print("reduce rate ===>", dfaug.shape[0], df_future_threds.shape[0], dfaug.shape[0] / df_future_threds.shape[0] )
    print(label_name, "==>", sent)
    t1 = time.time()
    print("time cost:", (t1-t0) / 60 )

    if dfaug.shape[0] == 0:
        print("reduct_empty")  
        continue 

    contents_syn = dfaug.head( args.max_aug_times )['content'].tolist()

    contents_syn_rnd = df_future_threds.sample(frac=1).head(len(contents_syn))['content'].tolist()

    arxivs.append((label, label_name, sent, \
                    "<sep>".join(dfaug.head(8)['content'].tolist()), \
                    "<sep>".join(df_future_threds.sample(frac=1).head(8)['content'].tolist()) ))

    for sent_syn  in contents_syn:
        print("gen==>", sent_syn, '\n\n' )
        infos.append((label, label_name, sent_syn ))

    for sent_syn  in contents_syn_rnd:
        #print("gen==>", sent_syn, '\n\n' )
        infos_rnd.append((label, label_name, sent_syn ))

    if len(arxivs) > 0 and len(arxivs) % 64 == 0:
        df_arxiv = pd.DataFrame(arxivs, columns=['label','label_name','content','content_syn_aug','content_syn_rnd'])
        df_arxiv.to_csv("df_arxiv_{}.csv".format(args.seed), index=False)
        print("df_arxiv saved ==>", df_arxiv.shape[0])

torch.cuda.empty_cache()


df_syn = pd.DataFrame(infos, columns=['label', 'label_name', 'content' ])
df_train_aug = pd.concat([ds.df_train, df_syn]).sample(frac=1)

df_syn_rnd = pd.DataFrame(infos_rnd, columns=['label', 'label_name', 'content' ])
df_train_aug_rnd = pd.concat([ds.df_train, df_syn_rnd]).sample(frac=1)

print("aug times:", df_syn.shape[0] / ds.df_train.shape[0])
print(df_train_aug.head(16))

# no aug
print("acc_noaug thread_testing")
acc_noaug  = thread_testing('test', ds.df_train, ds.df_test)

print("acc_aug thread_testing")
acc_aug = thread_testing('test', df_train_aug, ds.df_test)

print("acc_aug_rnd thread_testing")
acc_aug_rnd = thread_testing('test', df_train_aug_rnd, ds.df_test)

gain = (acc_aug - acc_noaug) / acc_noaug
gain_rnd = (acc_aug_rnd - acc_noaug) / acc_noaug

print("acc_summary==>", acc_noaug, acc_aug, acc_aug_rnd, gain, gain_rnd)



