#!/usr/bin/perl

use strict;
use warnings;

use DBI;
use Fcntl qw/:flock SEEK_END/;

require "./conf.pl";

our($db,$db_user,$db_pwd,$log_d,$doc_root,$upload_dir);

my %session;
my %auth_params;

my $id;
my $logd_in = 0;
my $authd = 0;
my $accountant = 0;

my $con;
my ($key,$iv,$cipher) = (undef, undef,undef);

if ( exists $ENV{"HTTP_SESSION"} ) {

	my @session_data = split/&/,$ENV{"HTTP_SESSION"};
	my @tuple;

	for my $unprocd_tuple (@session_data) {
		#came to learn (as often happens, purely by accident)
		#doing a split/=/,x= will give a list with a size of 1
		#desirable here (where it's OK to ignore unset vars)
		#would be awful where even a blank var means something (e.g
		#logging in with a blank password)
		@tuple = split/\=/,$unprocd_tuple;

		if (@tuple == 2) {
			$tuple[0] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$tuple[1] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$session{$tuple[0]} = $tuple[1];		
		}
	}

	#logged in 
	if (exists $session{"id"}) {
		$logd_in++;
		$id = $session{"id"};
		#only bursar(user 2) can publish a fee structure 
		if ( $id eq "2" ) {

			$accountant++;
			if (exists $session{"sess_key"} ) {
				$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

				use MIME::Base64 qw /decode_base64/;
				use Crypt::Rijndael;

				my $decoded = decode_base64($session{"sess_key"});
				my @decoded_bytes = unpack("C*", $decoded);

				my @sess_init_vec_bytes = splice(@decoded_bytes, 32);
				my @sess_key_bytes = @decoded_bytes;

				#read enc_keys_mem
				my $prep_stmt3 = $con->prepare("SELECT init_vec,aes_key FROM enc_keys_mem WHERE u_id=? LIMIT 1");

				if ( $prep_stmt3 ) {

					my $rc = $prep_stmt3->execute($id);

					if ( $rc ) {

						my ($mem_init_vec, $mem_aes_key) = (undef,undef);

						while (my @rslts = $prep_stmt3->fetchrow_array()) {
							$mem_init_vec = $rslts[0];
							$mem_aes_key = $rslts[1];
						}

						if ( defined $mem_init_vec ) {

							my @mem_init_vec_bytes = unpack("C*", $mem_init_vec);
							my @mem_aes_key_bytes = unpack("C*", $mem_aes_key);

							my ( @decrypted_init_vec, @decrypted_aes_key );

							for (my $i = 0; $i < @mem_init_vec_bytes; $i++) {
								$decrypted_init_vec[$i] = $mem_init_vec_bytes[$i] ^ $sess_init_vec_bytes[$i];
							}

							for (my $j = 0; $j < @mem_aes_key_bytes; $j++) {
								$decrypted_aes_key[$j] = $mem_aes_key_bytes[$j] ^ $sess_key_bytes[$j];
							}

							$key = pack("C*", @decrypted_aes_key);
							$iv = pack("C*", @decrypted_init_vec);

							$cipher = Crypt::Rijndael->new($key, Crypt::Rijndael::MODE_CBC());
							$cipher->set_iv($iv);

							$authd++;

						}
					}
					else {
						print STDERR "Couldn't execute SELECT FROM enc_keys_mem: ", $prep_stmt3->errstr, $/;
					}

				}
				else {
					print STDERR "Couldn't prepare SELECT FROM enc_keys_mem: ", $prep_stmt3->errstr, $/;
				}
			}
		}
	}
}

my $content = '';
my $feedback = '';
my $js = '';

my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Accounts Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/accounts/">Accounts</a> --&gt; <a href="/cgi-bin/fee_structure.cgi">New Fee Structure</a>
	<hr> 
};

unless ($authd) {
	if ($logd_in) {
		my $err = qq!<p><span style="color: red">Sorry, you do not have the appropriate privileges to alter the fee structure.</span> Only the bursar and accountant(s) are authorized to take this action.!;

		#key issues?
		if ( $accountant ) {

			$err = qq!<p><span style="color: red">Sorry, could not obtain the encryption keys needed to manage accounts.</span> Try <a href="/cgi-bin/logout.cgi">logging out</a> and then log in again. If this problem persists, contact support.!;

		}

		$content .=
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::Fee Structure</title>
</head>
<body>
$header

</body>
</html> 
*;
		print "Status: 200 OK\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";

		my $len = length($content);
		print "Content-Length: $len\r\n";

		my @new_sess_array = ();

		for my $sess_key (keys %session) {
			push @new_sess_array, $sess_key."=".$session{$sess_key};        
		}
		my $new_sess = join ('&',@new_sess_array);

		print "X-Update-Session: $new_sess\r\n";

		print "\r\n";
		print $content;
		exit 0;
	}
	else {
		print "Status: 302 Moved Temporarily\r\n";
		print "Location: /login.html?cont=/cgi-bin/fee_structure.cgi\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";
       		my $res = 
qq!
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::Fee Structure</title>
</head>
<body>
$header
You should have been redirected to <a href="/login.html?cont=/cgi-bin/fee_structure.cgi">/login.html?cont=/cgi-bin/fee_structure.cgi</a>. If you were not, <a href="login.html?cont=/cgi-bin/fee_structure.cgi">Click Here</a> 
</body>
</html>!;

		my $content_len = length($res);	
		print "Content-Length: $content_len\r\n";
		print "\r\n";
		print $res;
		exit 0;
	}
}

my $post_mode = 0;
my $boundary = undef;
my $multi_part = 0;

if (exists $ENV{"REQUEST_METHOD"} and uc($ENV{"REQUEST_METHOD"}) eq "POST") {
	

	if (exists $ENV{"CONTENT_TYPE"}) {
		if ($ENV{"CONTENT_TYPE"} =~ m!multipart/form-data;\sboundary=(.+)!i) {
			$boundary = $1;
			$multi_part++;
		}
	}

	unless ($multi_part) {
		my $str = "";

		while (<STDIN>) {
        	       	$str .= $_;
	       	}

		my $space = " ";
		$str =~ s/\x2B/$space/ge;
		my @auth_req = split/&/,$str;

		for my $auth_req_line (@auth_req) {
			my $eqs = index($auth_req_line, "=");	
			if ($eqs > 0) {
				my ($k, $v) = (substr($auth_req_line, 0, $eqs), substr($auth_req_line, $eqs + 1));
				$k =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
				$v =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
				$auth_params{$k} = $v;
			}
		}
	}
	#processing data sent 
	$post_mode++;
}

PM: {
if ($post_mode) {

	#valid,non-automated request
	if ( not exists $auth_params{"confirm_code"} or not exists $session{"confirm_code"} or $auth_params{"confirm_code"} ne $session{"confirm_code"} ) {
		$feedback = qq!<span style="color: red">Invalid tokens sent.</span>!;
		$post_mode = 0;
		last PM;
	}

	my $convert_to_arrears = 0;
	if ( exists $auth_params{"convert_to_arrears"} ) {
		$convert_to_arrears++;
	}

	use Digest::HMAC_SHA1 qw/hmac_sha1_hex/;

	#classes
	my %rolls = ();
	my %root_voteheads = ();
	my %votehead_indeces = ();

	my %votehead_exceptions = ();

	for my $auth_param ( keys %auth_params ) {
		if ($auth_param =~ /^classes_(.+)/) {
			$rolls{$auth_params{$auth_param}} = $1;
		}

		elsif ( $auth_param =~ /^index_votehead_(.+)$/) { 

			my $votehead = $1;

			if ($auth_params{$auth_param} =~ /^\d+$/) {

				my $index = $auth_params{$auth_param};
				#to leave room for arrears
				$index++;

				#lookup table for those voteheads where most students are not charged
				#anything but some are charged
				$votehead_indeces{$votehead} = $index;

				if ( exists $auth_params{"amount_votehead_$votehead"} and $auth_params{"amount_votehead_$votehead"} =~ /^\d+(?:\.\d{1,2})?$/ ) {
		
					my $amount = $auth_params{"amount_votehead_$votehead"};
					$root_voteheads{$votehead} = {"amount" => $amount, "index" => $index};
				}
			}

		}

		elsif ( $auth_param =~ /^class_exception_votehead_(?:.+)_(\d+)_(.+)$/ ) {

			my $cntr = $1;
			my $votehead = $2;

			my $roll = $auth_params{$auth_param};

			if ( exists $auth_params{"exception_votehead_${cntr}_${votehead}"} and $auth_params{"exception_votehead_${cntr}_${votehead}"} =~ /^\d+(?:\.\d{1,2})?$/ ) {

				my $amount = $auth_params{"exception_votehead_${cntr}_${votehead}"};
				${$votehead_exceptions{$roll}}{$votehead} = $amount;

			}
		}
	}

	unless ( scalar(keys %rolls) > 0 ) {
		$feedback = qq!<span style="color: red">You did not specify the classes you would like to apply this fee structure to.</span>!;
		$post_mode = 0;
		last PM;
	}

	#check for any exception voteheads without
	#root voteheads
	#create those root voteheads
	#with amounts of 0
	#I'm paranoid abt this, I don't
	#know why
	for my $exception_roll ( keys %votehead_exceptions ) {

		for my $votehead (keys %{$votehead_exceptions{$exception_roll}}) {

			if ( exists $votehead_indeces{$votehead} ) {

				if ( not exists $root_voteheads{$votehead} ) {
					$root_voteheads{$votehead} = {"amount" => 0, "index" => $votehead_indeces{$votehead}};	
				}

			}

		}

	}
	
	#TRUNCATE fee structure
	$con->do("TRUNCATE TABLE fee_structure");
	
	my $prep_stmt0 = $con->prepare("INSERT INTO fee_structure VALUES(?,?,?,?,?)");	
	
	if ($prep_stmt0) {

		for my $root_votehead (keys %root_voteheads) {

			my $enc_index = $cipher->encrypt(add_padding($root_voteheads{$root_votehead}->{"index"}));
			my $enc_votehead = $cipher->encrypt(add_padding($root_votehead));
			my $enc_class = $cipher->encrypt(add_padding(""));
			my $enc_amnt = $cipher->encrypt(add_padding($root_voteheads{$root_votehead}->{"amount"}));
	
			#class is blank so disregard it
			my $hmac = uc(hmac_sha1_hex($root_voteheads{$root_votehead}->{"index"} . $root_votehead . $root_voteheads{$root_votehead}->{"amount"} , $key));

			my $rc = $prep_stmt0->execute($enc_index, $enc_votehead, $enc_class, $enc_amnt, $hmac);

			unless ( $rc ) {
				print STDERR "Couldn't execute INSERT INTO fee_structure: ", $prep_stmt0->errstr, $/;
			}
		}

		#exceptions
		for my $exception_roll ( keys %votehead_exceptions ) {

			for my $votehead (keys %{$votehead_exceptions{$exception_roll}}) {

				if ( exists $votehead_indeces{$votehead} ) {

					my $enc_index = $cipher->encrypt(add_padding($votehead_indeces{$votehead}));
					my $enc_votehead = $cipher->encrypt(add_padding($votehead));
					my $enc_class = $cipher->encrypt(add_padding($exception_roll));

					my $enc_amnt = $cipher->encrypt(add_padding($votehead_exceptions{$exception_roll}->{$votehead}));

					my $hmac = uc(hmac_sha1_hex($votehead_indeces{$votehead} . $votehead . $exception_roll . $votehead_exceptions{$exception_roll}->{$votehead}, $key));

					my $rc = $prep_stmt0->execute($enc_index, $enc_votehead, $enc_class, $enc_amnt, $hmac);

					unless ( $rc ) {
						print STDERR "Couldn't execute INSERT INTO fee_structure: ", $prep_stmt0->errstr, $/;
					}

				}
			}
		}
	}
	else {
		print STDERR "Couldn't prepare INSERT INTO fee_structure: ", $prep_stmt0->errstr, $/;
	}

	#write 
	#read DB for all relevant records
	my @accounts_to_del;
	my %stud_balances = ();

	#read adms table to determine all studs
	#of interest
	my %studs = ();
	my @where_clause_bts = ();

	for my $roll (keys %rolls) {
		push @where_clause_bts, "table_name=?";
	}

	my $where_clause = join(" OR ", @where_clause_bts);

	my $prep_stmt4 = $con->prepare("SELECT adm_no,table_name FROM adms WHERE $where_clause");

	if ( $prep_stmt4 ) {

		my $rc = $prep_stmt4->execute(keys %rolls);

		if ($rc) {
			while ( my @rslts = $prep_stmt4->fetchrow_array() ) {
				${$studs{$rslts[0]}}{"roll"} = $rslts[1];
			}
		}
		else {
			print STDERR "Could not execute SELECT FROM adms statement: ", $prep_stmt4->errstr, $/;
		}
	
	}
	else {
		print STDERR "Could not prepare SELECT FROM adms statement: ", $prep_stmt4->errstr, $/;
	}

	my %old_accounts = ();

	my $prep_stmt3 = $con->prepare("SELECT account_name,class,amount,hmac FROM account_balances");

	if ($prep_stmt3) {
	
		my $rc = $prep_stmt3->execute();

		if ($rc) {

			while ( my @rslts = $prep_stmt3->fetchrow_array() ) {
									
				my $decrypted_account_name = $cipher->decrypt($rslts[0]);
				my $decrypted_class = $cipher->decrypt($rslts[1]);
				my $decrypted_amount = $cipher->decrypt($rslts[2]);

				my $account_name = remove_padding($decrypted_account_name);
				my $class = remove_padding($decrypted_class);
				my $amount = remove_padding($decrypted_amount);

				#valid decryption
				if ( $amount =~ /^\-?\d{1,10}(\.\d{1,2})?$/ ) {

					my $hmac = uc(hmac_sha1_hex($account_name . $class . $amount, $key));

					#auth the data
					if ( $hmac eq $rslts[3] ) {
						if ($account_name =~ /^(\d+)\-/) {
							my $adm_no = $1;
							my $votehead = substr($account_name, length($adm_no) + 1);
							#had a bug related with the
							#source of truth for a student's current
							#class. means the 'class' field which I
							#have all over is useless
							if ( exists $studs{$adm_no} ) {

								if ($convert_to_arrears) {
									$stud_balances{$adm_no} += $amount;
								}
								else {
									if ( $votehead eq "arrears" ) {
										$stud_balances{$adm_no} += $amount;
									}
									else {
										$old_accounts{$adm_no}->{$votehead} = $amount;
									}
								}

								push @accounts_to_del, $rslts[0];
							}
						}
					}
				}
			}
		}
		else {
			print STDERR "Couldn't execute SELECT FROM account_balances: ", $prep_stmt3->errstr, $/;
		}

	}

	else {
		print STDERR "Couldn't prepare SELECT FROM account_balances: ", $prep_stmt3->errstr, $/;
	}
		

	#delete old accounts
	my $prep_stmt5 = $con->prepare("DELETE FROM account_balances WHERE BINARY account_name=? LIMIT 1");

	if ($prep_stmt5) {

		foreach (@accounts_to_del) {

			my $rc = $prep_stmt5->execute($_);
			unless ($rc) {
				print STDERR "Couldn't execute DELETE FROM account_balances: ", $prep_stmt5->errstr, $/;	
			}

		}
	}
	else {
		print STDERR "Couldn't prepare DELETE FROM account_balances: ", $prep_stmt5->errstr, $/;
	}

	#do this here to allow INSERT INTO account_balances later
	$con->commit();

	my %cash_book_updates = ();
	my %new_accounts;
	my %fee_updates = ();
	my %prepayment_write_offs = ();

	my $time = time;

	#root voteheads
	for my $votehead (sort { $votehead_indeces{$a} <=> $votehead_indeces{$b} } keys %root_voteheads) {

		for my $stud (keys %studs) {

			my $roll = $studs{$stud}->{"roll"};
			my $amount = $root_voteheads{$votehead}->{"amount"};

			if ( exists ${$votehead_exceptions{$roll}}{$votehead} ) {
				$amount = ${$votehead_exceptions{$roll}}{$votehead};
			}

			my $lc_votehead = lc($votehead);

			$fee_updates{$stud . "-" . $lc_votehead} = {"amount" => $amount, "roll" => $roll};

			unless ($convert_to_arrears) {
				if ( exists $old_accounts{$stud}->{$lc_votehead} ) {
					$amount += $old_accounts{$stud}->{$lc_votehead};
				}
			}

			#check if stud has a pre-payment
			if ( exists $stud_balances{$stud} and $stud_balances{$stud} < 0 ) {
	
				my $pre_payment = $stud_balances{$stud} * -1;

				#the prepayment can completely clear this amount
				if ($pre_payment > $amount) {

					$prepayment_write_offs{$stud} += $amount;

					$pre_payment -= $amount;
					#a bug was found where if a student has a large
					#enough prepayment that covers fees for several
					#terms, there would be a collision in the entry made
					#to the cashbook. Fix this by including time in the receipt no.
					$cash_book_updates{ "Prepayment($stud-$time)-" . $lc_votehead } = {"votehead" => $lc_votehead, "amount" => $amount};
					$amount = 0;
					$stud_balances{$stud} = $pre_payment * -1;

				}

				else {

					$prepayment_write_offs{$stud} += $pre_payment;

					$amount -= $pre_payment;
					$cash_book_updates{ "Prepayment($stud-$time)-" . $lc_votehead } = {"votehead" => $lc_votehead, "amount" => $pre_payment};
					#eliminate this prepayment
					delete $stud_balances{$stud};

				}
				
			}

			#amount may have been cleared by prepayments
			if ($amount > 0) {
				#not  very elegant
				#wish I didn't (HAVE TO) duplicate
				#the 'roll'
				#could deduce the adm no. from the account name (and thus
				#the roll) but I'm paranaoid about that
				#I'll console myself that this' a cpu-memory tradeoff
				#
				$new_accounts{$stud . "-" . lc($votehead)} = {"amount" => $amount, "roll" => $roll}; 
			}
		}
	}
	
	my $encd_time = $cipher->encrypt(add_padding("".$time));

	my $prep_stmt6 = $con->prepare("INSERT INTO account_balances VALUES(?,?,?,?)");

	if ($prep_stmt6) {

		for my $stud (keys %stud_balances) {

			my $encd_accnt_name = $cipher->encrypt(add_padding("$stud-arrears"));
			my $encd_class = $cipher->encrypt(add_padding($studs{$stud}->{"roll"}));
			my $encd_amnt = $cipher->encrypt(add_padding($stud_balances{$stud}));

			my $hmac = uc(hmac_sha1_hex("$stud-arrears" . $studs{$stud}->{"roll"} . $stud_balances{$stud}, $key));

			my $rc = $prep_stmt6->execute($encd_accnt_name, $encd_class, $encd_amnt, $hmac);

			unless ($rc) {
				print STDERR "Couldn't execute INSERT INTO account_balances: ", $prep_stmt6->errstr, $/;
			}
		}

		for my $accnt (keys %new_accounts) {

			my $encd_accnt_name = $cipher->encrypt(add_padding($accnt));
			my $encd_class = $cipher->encrypt(add_padding($new_accounts{$accnt}->{"roll"}));
			my $encd_amnt = $cipher->encrypt(add_padding($new_accounts{$accnt}->{"amount"}));

			my $hmac = uc(hmac_sha1_hex($accnt . $new_accounts{$accnt}->{"roll"} . $new_accounts{$accnt}->{"amount"}, $key));

			my $rc = $prep_stmt6->execute($encd_accnt_name, $encd_class, $encd_amnt, $hmac);

			unless ($rc) {
				print STDERR "Couldn't execute INSERT INTO account_balances: ", $prep_stmt6->errstr, $/;
			}
		}
	}
	else {
		print STDERR "Couldn't prepare INSERT INTO account_balances: ", $prep_stmt6->errstr, $/;
	}

	#add to account_balance_updates log
	my $prep_stmt7 = $con->prepare("INSERT INTO account_balance_updates VALUES(?,?,?,?)");

	if ( $prep_stmt7 ) {

		for my $accnt (keys %fee_updates) {

			my $encd_accnt_name = $cipher->encrypt(add_padding($accnt));	
			my $encd_amnt = $cipher->encrypt(add_padding($fee_updates{$accnt}->{"amount"}));

			my $hmac = uc(hmac_sha1_hex($accnt . $fee_updates{$accnt}->{"amount"} . $time, $key));

			my $rc = $prep_stmt7->execute($encd_accnt_name, $encd_amnt, $encd_time, $hmac);

			unless ($rc) {
				print STDERR "Couldn't execute INSERT INTO account_balance_updates: ", $prep_stmt7->errstr, $/;
			}
		}

	}
	else {
		print STDERR "Couldn't prepare INSERT INTO account_balance_updates: ", $prep_stmt7->errstr, $/;
	}

	#cancel any prepayments
	if ( scalar(keys %prepayment_write_offs) > 0 ) {
			
		my $prep_stmt8 = $con->prepare("SELECT receipt_no,paid_in_by,class,amount,mode_payment,ref_id,votehead,time,hmac FROM receipts WHERE paid_in_by=?");

		if ($prep_stmt8) {

			#read any negative arrears--expect only 1 result
			my $prep_stmt9 = $con->prepare("SELECT receipt_votehead,votehead,amount,time,hmac FROM cash_book WHERE receipt_votehead=? LIMIT 1");

			if ($prep_stmt9) {

				#overwrite current 
			
				my %receipts = ();
				my %edited_cash_book_entries = ();

				for my $adm ( keys %prepayment_write_offs ) {
					#print "X-Debug-4-$adm: proc'ng prepayment\r\n";
					my $encd_adm = $cipher->encrypt(add_padding($adm));
	
					my $rc = $prep_stmt8->execute($encd_adm);

					if ($rc) {

						while ( my @rslts = $prep_stmt8->fetchrow_array() ) {

							my $receipt_no = $rslts[0];
							my $paid_in_by = remove_padding($cipher->decrypt($rslts[1]));
							my $class = remove_padding($cipher->decrypt($rslts[2]));
							my $amount = remove_padding($cipher->decrypt($rslts[3]));
							my $mode_payment = remove_padding($cipher->decrypt($rslts[4]));
							my $ref_id = remove_padding($cipher->decrypt($rslts[5]));
 							my $votehead = remove_padding($cipher->decrypt($rslts[6]));
							my $time = remove_padding($cipher->decrypt($rslts[7]));

							if ( $amount =~ /^\d{1,10}(\.\d{1,2})?$/ ) {

								my $hmac = uc(hmac_sha1_hex($paid_in_by . $class . $amount . $mode_payment . $ref_id . $votehead . $time, $key));

								if ( $hmac eq $rslts[8] ) {
									#record the time for sorting
									#print "X-Debug-$adm-$receipt_no: seen receipt for $amount\r\n";
									${$receipts{$adm}}{$receipt_no} = $time;
								}
							}	
						}
					}
					else {
						print STDERR "Couldn't execute SELECT FROM receipts: ", $prep_stmt8->errstr, $/;
					}
					#have I seen any receipts
					#perl is very quick to create hash keys
					#i use exists to avoid that here
					if ( exists $receipts{$adm} and scalar (keys %{$receipts{$adm}}) > 0 ) {

						my $prepayment_amnt = $prepayment_write_offs{$adm};
						#print "X-Debug-2-$adm: prepayment is $prepayment_amnt\r\n";

						#walk backwards through the receipts seen
						#the most relevant receipts are at the back
						JJ: for my $receipt ( sort {$receipts{$adm}->{$b} <=>  $receipts{$adm}->{$a}} keys %{$receipts{$adm}} ) {

							my $encd_receipt_votehead = $cipher->encrypt(add_padding($receipt . "-arrears"));
							my $rc = $prep_stmt9->execute($encd_receipt_votehead);

							if ( $rc ) {

								while ( my @rslts = $prep_stmt9->fetchrow_array() ) {

									my $receipt_votehead = remove_padding($cipher->decrypt($rslts[0]));
									my $votehead = remove_padding($cipher->decrypt($rslts[1]));
									my $amount = remove_padding($cipher->decrypt($rslts[2]));
									my $time = remove_padding($cipher->decrypt($rslts[3]));

									#amount must be negative i.e a prepayment
									if ( $amount =~ /^\-\d+(\.\d{1,2})?$/ ) {

										my $hmac = uc(hmac_sha1_hex($receipt_votehead . $votehead . $amount . $time, $key));
	
										if ( $hmac eq $rslts[4] ) {
											#print "X-Debug-3-$adm-$receipt_votehead: proc'ng amount of $amount\r\n";
											my $done = 0;
											#will this prepayment be cleared by this cash book entry?
											my $pre_amnt = $amount;
											if ( $prepayment_amnt <= ($amount * -1) ) {
												$amount += $prepayment_amnt;
												#break out--all debts have been settled
												$done++;
											}
											else {
												$prepayment_amnt -= ($amount * -1);
												$amount = 0;
											}
											
											my $n_hmac = uc(hmac_sha1_hex($receipt_votehead . $votehead . $amount . $time, $key));

											$edited_cash_book_entries{$receipt_votehead} = { "receipt_votehead" => $rslts[0], "votehead" => $rslts[1], "amount" => $cipher->encrypt(add_padding($amount)), "time" => $rslts[3], "hmac" => $n_hmac };
											#print "X-Debug-0-$n_hmac: updated amnt to $amount from $pre_amnt\r\n"; 
											if ($done) {
												last JJ;
											}
										}

									}
								}

							}
							else {
								print STDERR "Couldn't execute SELECT FROM cash_book: ", $prep_stmt9->errstr, $/;
							}
						}
					}
				}

				#commit any changes
				if ( scalar (keys %edited_cash_book_entries) > 0 ) {

					#print "X-Debug: updating prepayments\r\n";

					my $prep_stmt10 = $con->prepare("REPLACE INTO cash_book VALUES(?,?,?,?,?)");

					for my $receipt_votehead ( keys %edited_cash_book_entries ) {

						#print qq!X-Debug-$edited_cash_book_entries{$receipt_votehead}->{"hmac"}: updated amnt\r\n!;

						$prep_stmt10->execute($edited_cash_book_entries{$receipt_votehead}->{"receipt_votehead"}, $edited_cash_book_entries{$receipt_votehead}->{"votehead"}, $edited_cash_book_entries{$receipt_votehead}->{"amount"}, $edited_cash_book_entries{$receipt_votehead}->{"time"}, $edited_cash_book_entries{$receipt_votehead}->{"hmac"});

					}

				}
			}
			else {
				print STDERR "Couldn't execute SELECT FROM cash_book: ", $prep_stmt9->errstr, $/;
			}
		}
		else {
			print STDERR "Couldn't execute SELECT FROM receipts: ", $prep_stmt8->errstr, $/;
		}
	}

	#insert into cash_book
	my $prep_stmt8 = $con->prepare("INSERT INTO cash_book VALUES(?,?,?,?,?)");

	if ($prep_stmt8) {

		for my $prepayment (keys %cash_book_updates) {

			my $encd_prepayment = $cipher->encrypt(add_padding($prepayment));
			my $encd_votehead = $cipher->encrypt(add_padding($cash_book_updates{$prepayment}->{"votehead"}));
			my $encd_amount = $cipher->encrypt(add_padding($cash_book_updates{$prepayment}->{"amount"}));
			my $hmac = uc(hmac_sha1_hex($prepayment . $cash_book_updates{$prepayment}->{"votehead"} . $cash_book_updates{$prepayment}->{"amount"} . $time, $key));

			my $rc = $prep_stmt8->execute($encd_prepayment, $encd_votehead, $encd_amount, $encd_time, $hmac);

			unless ($rc) {
				print STDERR "Couldn't execute INSERT INTO cash_book: ", $prep_stmt8->errstr, $/;	
			}
		}

	}
	else {
		print STDERR "Couldn't prepare INSERT INTO cash_book: ", $prep_stmt8->errstr, $/;
	}

	
	#log action
	my @today = localtime;	
	my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];

	open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");
       	if ($log_f) {

		my $classes = join(", ", values(%rolls));

       		@today = localtime;	
		my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];	
		flock ($log_f, LOCK_EX) or print STDERR "Could not log publish fee structure for $id due to flock error: $!$/"; 
		seek ($log_f, 0, SEEK_END);
		print $log_f "$id PUBLISH FEE STRUCTURE $classes $time\n";
		flock ($log_f, LOCK_UN);
               	close $log_f;
       	}
	else {
		print STDERR "Could not log publish fee structure for $id: $!\n";
	}

	$con->commit();

	#any voteheads not processed as part ofroot
	$content = 
qq*
<!DOCTYPE html>
<html lang="en">

<head>
<title>Spanj::Accounts Management Information System::Update Fee Balances</title>
</head>

<body>
$header
<p><span style="color: green">The new fee structure has been applied!</span>. You can view the new fee balances on the <a href="/cgi-bin/fee_balances.cgi">fee balances page</a>
</body>
</html>
*;

}
}

if (not $post_mode) {

	use Digest::HMAC_SHA1 qw/hmac_sha1_hex/;

	my $current_yr = (localtime)[5] + 1900; 
	my %grouped_classes = ("1"=> "1", "2"=> "2", "3"=> "3","4"=> "4");
	
	my $prep_stmt = $con->prepare("SELECT value FROM vars WHERE id='1-classes' LIMIT 1");

	if ($prep_stmt) {
		my $rc = $prep_stmt->execute();
		if ($rc) {
			while (my @rslts = $prep_stmt->fetchrow_array()) {
				my @classes = split/,/, $rslts[0];
				%grouped_classes = ();
				for my $class (@classes) {
					if ($class =~ /(\d+)/) {	
						$grouped_classes{$1}->{$class}++;
					}
				}
			}
		}
	}

	my %class_table_lookup = ();
	my %table_class_lookup = ();

	my $prep_stmt1 = $con->prepare("SELECT table_name,class,start_year FROM student_rolls WHERE grad_year >= ?");

	if ($prep_stmt1) {

		my $rc = $prep_stmt1->execute($current_yr);
		if ($rc) {	
			while ( my @rslts = $prep_stmt1->fetchrow_array() ) {

				my $class = $rslts[1];
				my $class_yr = ($current_yr - $rslts[2]) + 1;
				
				$class =~ s/\d+/$class_yr/;

				$class_table_lookup{$class} = $rslts[0];
				$table_class_lookup{$rslts[0]} = $class;

			}
		}
		else {
			print STDERR "Couldn't execute SELECT FROM student_rolls: ", $prep_stmt1->errstr, $/;
		}
	}
	else {
		print STDERR "Couldn't prepare SELECT FROM student_rolls: ", $prep_stmt1->errstr, $/;
	}


	my @class_yr_js_hashes = ();
	my $classes_select = qq!<TABLE cellpadding="5%" cellspacing="5%"><TR>!;

	for my $class_yr (sort {$a <=> $b} keys %grouped_classes) {

		my @class_yr_members = ();
		$classes_select .= "<TD>";

		my @classes = keys %{$grouped_classes{$class_yr}};
		
		for my $class (sort {$a cmp $b} @classes) {
			if ( exists $class_table_lookup{$class} ) {
				$classes_select .= qq!<INPUT type="checkbox" checked name="classes_$class" value="$class_table_lookup{$class}"><LABEL for="class_$class">$class</LABEL><BR>!;	
				push @class_yr_members, "{class: '$class', roll: '$class_table_lookup{$class}'}";
			}
		}

		my $class_yr_members_str = join(", ", @class_yr_members);
 
		push @class_yr_js_hashes, "{year: $class_yr, members: [$class_yr_members_str]}";
	}

	$classes_select .= "</TABLE>";

	my $classes_js = join(", ", @class_yr_js_hashes);
 	
	my %votehead_hierarchy = ();

	my $prep_stmt4 = $con->prepare("SELECT votehead,votehead_parent,amount,hmac FROM budget");
	
	if ( $prep_stmt4 ) {

		my $rc = $prep_stmt4->execute();
	
		if ( $rc ) {

			while (my @rslts = $prep_stmt4->fetchrow_array()) {		

				my $decrypted_votehead = $cipher->decrypt( $rslts[0] );
				my $votehead = remove_padding($decrypted_votehead);

				my $decrypted_votehead_parent = $cipher->decrypt( $rslts[1] );
				my $votehead_parent = remove_padding($decrypted_votehead_parent);

				my $decrypted_amnt = $cipher->decrypt( $rslts[2] );	
				my $amnt = remove_padding($decrypted_amnt);

				#valid decryption
				if ( $amnt =~ /^\-?\d+(\.\d{1,2})?$/ ) {
					#check HMAC
					my $hmac = uc(hmac_sha1_hex($votehead . $votehead_parent . $amnt, $key));	
					if ( $hmac eq $rslts[3] ) {
						#did this to enable even parents
						#to record their budget amounts 
						my $parent = 0;
						if ( $votehead_parent eq "" ) {
							$votehead_parent = $votehead;
							$parent = 1;
						}
						${$votehead_hierarchy{$votehead_parent}}{$votehead}++;
					}
				}
			}
			
		}
		else {
			print STDERR "Couldn't execute SELECT FROM budget: ", $prep_stmt4->errstr, $/;
		}
	}
	else {
		print STDERR "Couldn't prepare SELECT FROM budget: ", $prep_stmt4->errstr, $/;
	}

	my $start = 1947;
	my %votehead_indeces = ();

	for my $votehead (keys %votehead_hierarchy) {

		$votehead_indeces{$votehead} = {"index" => $start++, "parent" => 1};
		for my $child_votehead (keys %{$votehead_hierarchy{$votehead}}) {

			next if ($votehead eq $child_votehead);
			$votehead_indeces{$child_votehead} = {"index" => $start++, "parent" => 0};

		}
	}
	
	my $cntr = 0;
	my %fee_structure = ();	

	#read fee structure
	my $prep_stmt2 = $con->prepare("SELECT votehead_index,votehead_name,class,amount,hmac FROM fee_structure");
	
	if ($prep_stmt2) {
	
		my $rc = $prep_stmt2->execute();
		if ($rc) {
			while ( my @rslts = $prep_stmt2->fetchrow_array() ) {
						
				my $decrypted_votehead_index = $cipher->decrypt($rslts[0]);
				my $decrypted_votehead_name = $cipher->decrypt($rslts[1]);
				my $decrypted_class = $cipher->decrypt($rslts[2]);
				my $decrypted_amount = $cipher->decrypt($rslts[3]);

				my $votehead_index = remove_padding($decrypted_votehead_index);
				my $votehead_name = remove_padding($decrypted_votehead_name);
				my $class = remove_padding($decrypted_class);
				my $amount = remove_padding($decrypted_amount);
	
				#valid decryption
				if ( $amount =~ /^\-?\d{1,10}(\.\d{1,2})?$/ ) {

					my $hmac = uc(hmac_sha1_hex($votehead_index . $votehead_name . $class . $amount, $key));
								
					#auth the data
					if ( $hmac eq $rslts[4] ) {	
						$fee_structure{$cntr++} = {"name" => $votehead_name, "index" => $votehead_index, "class" => $class, "amount" => $amount};
						${$votehead_indeces{$votehead_name}}{"index"} = $votehead_index;
					}
				}
			}
		}
		else {
			print STDERR "Couldn't execute SELECT FROM fee_structure: ", $prep_stmt2->errstr, $/;
		}
	}
	else {
		print STDERR "Couldn't prepare SELECT FROM fee_structure: ", $prep_stmt2->errstr, $/;
	}

	my @votehead_indeces_js_bts = ();

	#keep voteheads sorted in JS
	#then I can move up/down without
	#sorting
	for my $votehead_1 ( sort { $votehead_indeces{$a}->{"index"} <=> $votehead_indeces{$b}->{"index"} } keys %votehead_indeces ) {

		my $escaped = htmlspecialchars($votehead_1);	
		push @votehead_indeces_js_bts, qq!"$escaped"!;
	}

	my $votehead_indeces_js_str = join(",", @votehead_indeces_js_bts);

	$cntr = 0;
	my $voteheads = qq!<div id="voteheads">!;
	
	for my $votehead ( sort { $votehead_indeces{$a}->{"index"} <=> $votehead_indeces{$b}->{"index"} } keys %votehead_indeces ) {

		my $escaped_votehead = htmlspecialchars($votehead);
		
		my $spacer = "&nbsp;" x 5;

		if (${$votehead_indeces{$votehead}}{"parent"}) {
			$spacer = "";
		}

		my $root_amnt = "";
		my %votehead_exceptions;

		for my $votehead_1 (keys %fee_structure) {

			if ( ${$fee_structure{$votehead_1}}{"name"} eq $votehead ) {

				my $class = ${$fee_structure{$votehead_1}}{"class"};
				my $amnt = ${$fee_structure{$votehead_1}}{"amount"};

				#the root
				if ( $class eq "" ) {
					$root_amnt = $amnt;
				}
				else {
					${$votehead_exceptions{$amnt}}{$class}++;
				}
			}
		}
	
		$voteheads .= qq!<div id="container_$escaped_votehead">!;
		#votehead_index
		$voteheads .= qq!<INPUT type="hidden" value="$cntr" name="index_votehead_$escaped_votehead" id="index_votehead_$escaped_votehead">!;
		$cntr++;

		#root
		$voteheads .= qq!$spacer<LABEL style="font-weight: bold" for="amount_votehead_$escaped_votehead">$escaped_votehead</LABEL>&nbsp;&nbsp;<span style="color: red" id="amount_votehead_${escaped_votehead}_err"></span><INPUT type="text" value="$root_amnt" name="amount_votehead_$escaped_votehead" id="amount_votehead_$escaped_votehead" onkeyup="check_amount('amount_votehead_$escaped_votehead')" onmouseover="check_amount('amount_votehead_$escaped_votehead')">&nbsp;&nbsp;<a href="javascript:move('$escaped_votehead', true)" id="move_up_$escaped_votehead">Move up</a>|<a href="javascript:move('$escaped_votehead', false)" id="move_down_$escaped_votehead">Move down</a>&nbsp;&nbsp;<input type="button" value="Add Exception" onclick="add_exception('$spacer', '$escaped_votehead')"><br><br>!;

		#exceptions
		for my $amnt ( keys %votehead_exceptions ) {
			#add list of classes

			$voteheads .= qq!<div style="margin-left: 5em"><TABLE cellspacing="5%" cellpadding="5%"><TR>!;

			for my $class_yr (sort {$a <=> $b} keys %grouped_classes) {

				$voteheads .= "<TD>";

				my @classes = keys %{$grouped_classes{$class_yr}};
		
				for my $class (sort {$a cmp $b} @classes) {
					if ( exists $class_table_lookup{$class} ) {

						my $roll = $class_table_lookup{$class};
						my $checked = "";
	
						if (exists $votehead_exceptions{$amnt}->{$roll}) {
							$checked = " checked";
						}

						$voteheads .= qq!<INPUT type="checkbox"$checked name="class_exception_votehead_${class}_${cntr}_${escaped_votehead}" value="$roll"><LABEL for="class_exception_votehead_${cntr}_$escaped_votehead">$class</LABEL><BR>!;
					}
				}
			}

			$voteheads .= qq!<TD style="border-left: solid"><LABEL for="exception_votehead_${cntr}_$escaped_votehead">Amount</LABEL>&nbsp;&nbsp;<span style="color: red" id="exception_votehead_${cntr}_${escaped_votehead}_err"></span><INPUT type="text" value="$amnt" name="exception_votehead_${cntr}_$escaped_votehead" id="exception_votehead_${cntr}_$escaped_votehead" onkeyup="check_amount('exception_votehead_${cntr}_$escaped_votehead')" onmouseover="check_amount('exception_votehead_${cntr}_$escaped_votehead')"></TABLE></div>!;
			$cntr++;
		}

		$voteheads .= "</div>";	
	}

	$voteheads .= "</div>";

	my $conf_code = gen_token();
	$session{"confirm_code"} = $conf_code;

	$content = 
qq*
<!DOCTYPE html>
<html lang="en">

<head>
<title>Spanj::Accounts Management Information System::Publish New Fee Structure</title>

<script type="text/javascript">

var num_re = /^([0-9]{0,10})(\\.([0-9]{0,2}))?\$/;
var classes = [$classes_js];
var votehead_indeces = [$votehead_indeces_js_str];
var link_color = "blue";
var votehead_cntr = $cntr;

function init() {
	if ( votehead_indeces.length > 0 ) {
		link_color = document.getElementById("move_up_" + votehead_indeces[0]).style.color;
	}
}

function check_amount(elem) {

	var amnt = document.getElementById(elem).value;
	var match_groups = amnt.match(num_re);

	if ( match_groups ) {
		document.getElementById(elem + "_err").innerHTML = "";
	}
	else {
		document.getElementById(elem + "_err").innerHTML = "\*";
	}
}

function move( elem, up_down ) {

	var len = votehead_indeces.length;

	for ( var i = 0; i < len; i++ ) {

		if ( votehead_indeces[i] == elem ) {

			if (up_down) {
				if ( i == 0 ) {	
					document.getElementById("move_up_" + elem).style.color = "grey";
					break;
				}
			}

			if(!up_down) {
				if ( i == len - 1 ) {
					document.getElementById("move_down_" + elem).style.color = "grey";
					break;
				}
			}

			var swap_with = i + 1;	

			if (up_down) {
				swap_with = i - 1;
			}
	
			var tmp = votehead_indeces[swap_with];

			votehead_indeces[swap_with] = elem;
			votehead_indeces[i] = tmp;	

			var elems = [];	

			for (var i = 0; i < len; i++) {

				document.getElementById("index_votehead_" + votehead_indeces[i]).value = i;

				var child = document.getElementById("container_" + votehead_indeces[i]);
				var removed = child.parentNode.removeChild(child);
				elems.push(removed);

				
			}

			for ( var j = 0; j < elems.length; j++ ) {
				document.getElementById("voteheads").appendChild(elems[j]);
			}

			document.getElementById("move_up_" + elem).style.color = link_color;
			document.getElementById("move_down_" + elem).style.color = link_color;

			break;
		}
	}
}

function add_exception(prefix, votehead) {

	var classes_select = '<TABLE cellspacing="5%" cellpadding="5%"><TR>';

	for ( var i = 0; i < classes.length; i++) {

		classes_select += '<TD>';

		var classes_in_yr = classes[i].members;		
		for ( var j = 0; j < classes_in_yr.length; j++ ) {

			classes_select += '<LABEL for="class_exception_votehead_' + classes_in_yr[j].class  + '_' + votehead_cntr + '_' + votehead + '"></LABEL>' + classes_in_yr[j].class + '<INPUT type="checkbox" name="class_exception_votehead_' + classes_in_yr[j].class + '_' + votehead_cntr + '_' + votehead + '" value="' + classes_in_yr[j].roll + '"><BR>';

		}
	}

	var new_exception = document.createElement("div");

	var left_margin = 5;
	if (prefix.length > 0) {
		left_margin += 5;
	}

	new_exception.style.marginLeft = left_margin + "em";

	new_exception.innerHTML =  classes_select + '<TD><LABEL for="exception_votehead_' + votehead_cntr + '_' + votehead + '">Amount</LABEL>&nbsp;&nbsp;<span style="color: red" id="exception_votehead_' + votehead_cntr + '_' + votehead + '_err"></span><INPUT type="text" name="exception_votehead_' + votehead_cntr + '_' + votehead + '" id="exception_votehead_' + votehead_cntr + '_' + votehead + '" onkeyup="check_amount(\\'exception_votehead_' + votehead_cntr + '_' + votehead + '\\')" onmouseover="check_amount(\\'exception_votehead_' + votehead_cntr + '_' + votehead + '\\')"></TABLE>';

	document.getElementById("container_" + votehead).appendChild(new_exception);

	var root_val = document.getElementById("amount_votehead_" + votehead).value;

	if ( root_val.length == 0 ) {
		document.getElementById("amount_votehead_" + votehead).value = "0";
	}

	votehead_cntr++;

}
</script>

</head>

<body onload="init()">
$header
$feedback
<p>This page allows you to update fee balances(e.g. at the start of a new term).<p><span style="font-weight: bold">NOTE:</span>All current fee balances will be <span style="font-weight: bold">converted to arrears</span> if the relevant checkbox is checked.

<FORM method="POST" action="/cgi-bin/fee_structure.cgi">

<h4>Convert Balances to Arrears?</h4>
<p>Convert all current balances to arrears?&nbsp;&nbsp;<INPUT type="checkbox" name="convert_to_arrears">
<h4>Classes</h4>
<p>Which classes do you want to apply this fee structure to?

$classes_select

<input type="hidden" name="confirm_code" value="$conf_code">
<h4>Voteheads</h4>
<p>You can change the order in which fee payments are processed by moving voteheads up or down.
$voteheads
<p><INPUT type="submit" value="Apply Fee Structure" name="apply">
</FORM>

</body>

</html>
*;
}

print "Status: 200 OK\r\n";
print "Content-Type: text/html; charset=UTF-8\r\n";

my $len = length($content);
print "Content-Length: $len\r\n";

my @new_sess_array = ();

for my $sess_key (keys %session) {
	push @new_sess_array, $sess_key."=".$session{$sess_key};        
}
my $new_sess = join ('&',@new_sess_array);

print "X-Update-Session: $new_sess\r\n";

print "\r\n";
print $content;
$con->disconnect() if (defined $con and $con);

sub gen_token {
	my @key_space = ("A","B","C","D","E","F","0","1","2","3","4","5","6","7","8","9");
	my $len = 5 + int(rand 15);
	if (@_ and ($_[0] eq "1")) {
		@key_space = ("A","B","C","D","E","F","G","H","J","K","L","M","N","P","T","W","X","Z","7","0","1","2","3","4","5","6","7","8","9");
		$len = 10 + int (rand 5);
	}
	my $token = "";
	for (my $i = 0; $i < $len; $i++) {
		$token .= $key_space[int(rand @key_space)];
	}
	return $token;
}

sub htmlspecialchars {
	my $cp = $_[0];
	#$cp =~ s/&/&#38;/g;
        $cp =~ s/</&#60;/g;
        $cp =~ s/>/&#62;/g;
        $cp =~ s/'/&#39;/g;
        $cp =~ s/"/&#34;/g;
        return $cp;
}

sub remove_padding {

	return undef unless (@_);

	my $packed = $_[0];
	my @bytes = unpack("C*", $packed);
	
	my $final_index = $#bytes;
	my $pad_size = $bytes[$final_index];

	my $msg_valid = 1;
	#verify msg
	
	for ( my $i = 1; $i < $pad_size; $i++ ) {
		unless ( $bytes[$final_index - $i] == $pad_size ) {
			$msg_valid = 0;
			last;
		}
	}

	if ($msg_valid) {
		my $msg_size = ($final_index + 1) - $pad_size;
		my $msg = unpack("A${msg_size}", $packed);

		return $msg;
	}
	return undef;
}

sub add_padding {

	return undef unless (@_);

	my $tst_str = $_[0];
	my $tst_str_len = length($tst_str);

	my $rem = 16 - ($tst_str_len % 16);
	if ($rem == 0 ) {
		$rem = 16;
	}

	my @extras = ();
	for (my $i = 0; $i < $rem; $i++) {
		push @extras, $rem;
	}

	my $padded = pack("A${tst_str_len}C${rem}", $tst_str, @extras);
	return $padded;
}

sub format_currency {

	return "" unless (@_);

	my $formatted_num = $_[0];

	if ( $_[0] =~ /^(\-?)(\d+)(\.(?:\d))?$/ ) {

		my $sign = $1;
		my $shs = $2;
		my $cents = $3;

		$sign = "" if (not defined $sign);
		$cents = "" if (not defined $cents);

		my $num_blocks = int(length($shs) / 3);

		if ($num_blocks > 0) {

			my @nums = ();

			my $surplus = length($shs) % 3;
			if ($surplus > 0) {
				push @nums, substr($shs, 0, $surplus);
			}

			for (my $i = 0; $i < $num_blocks; $i++) {
				push @nums, substr($shs, $surplus + ($i * 3),3);
			}

			$formatted_num = join(",", @nums); 
		}

		$formatted_num = $sign . $formatted_num;
		$formatted_num .= $cents;
	}
	return $formatted_num;
}
