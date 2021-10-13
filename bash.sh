conda config --set auto_activate_base true

###




ps aux|grep ttt|grep -v grep | awk '{print $2}'|xargs kill -9


tf_upgrade_v2 --infile main_data_valuation.py --outfile main_data_valuation_v2.py


##### augf


nohup python -u augf.py --dsn ag --samplecnt 32 --max_aug_times 1 --aug generate  \
	 --genft no --filter nli,cls,nsp,enc,dvrl --genm gpt --abundance 3 --basetry 1 --epochs 60 --freq 30 > augf.log & 


nohup python -u augf.py --dsn ag --samplecnt 32 --max_aug_times 1 --aug generate  \
	 --genft no --filter nli,dvrl --genm gpt --abundance 3 --basetry 1 --epochs 60 --freq 30 > augf.filter2.log & 


nohup python -u augf.py --dsn ag --samplecnt 128 --max_aug_times 1 --aug generate \
				      --genft no  --genm gpt --filter dvrl --abundance 3  --basetry 1 \
				      --verbose 1 --epochs 100 --freq 50 > augf.test.log & 




# 解压
unzip -o -d /home/sunny myfile.zip



# 压缩

for file in torch_ds resource cache cache_cbert
do
	#tar -zcvf ${file}.tar.gz ${file}
	tar -xvzf ${file}.tar.gz  -C ${file}
done


zip -r myfile.zip ./myfile


scp resource.tar.gz root@sdu:/home/yanan/topic_classification_augmentation/




CUDA_VISIBLE_DEVICES=6 ./envcbert/bin/python -u ft_t5.py --ft_pattern pp --num_workers 4  \
   --maxlen 512 --ccsample 0.4 --ftepochs 7 --batch_size 8 



python -u ft_gpt2.py --genm gpt2 --num_train_epochs 4 --ccsample 1 --ft_pattern tc --gpu 6 





############## ft gpt 
nohup python -u ft_gpt2.py --genm gpt2 --num_train_epochs 4 --ccsample 1 --ft_pattern tc --gpu 6  --batch_size 8 \
 > ft.gpt2.tc.log &

nohup python -u ft_gpt2.py --genm gpt2 --num_train_epochs 4 --ccsample 1 --ft_pattern pp  --gpu 7  \
 > ft.gpt2.pp.log &


# ft t5
CUDA_VISIBLE_DEVICES=7 nohup ./envcbert/bin/python -u ft_t5.py --ft_pattern pp --num_workers 4  \
   --maxlen 512 --ccsample 0.4 --ftepochs 7 --batch_size 8 > ft.t5.pp.log & 

CUDA_VISIBLE_DEVICES=0 nohup ./envcbert/bin/python -u ft_t5.py --ft_pattern tc --num_workers 1 \
   --maxlen 512 --ccsample 0.35 --ftepochs 4 --batch_size 8 > ft.t5.tc.log & 



CUDA_VISIBLE_DEVICES=7 ./envcbert/bin/python -u ft_t5.py --ft_pattern tc --num_workers 4  \
   --maxlen 512 --ccsample 1 --ftepochs 7 --batch_size 8


